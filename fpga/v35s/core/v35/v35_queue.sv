`timescale 1ns/1ps

// V35S core v2: the prefetch queue (docs/v35s-core-v2.md, "Modules and the state they own";
// Appendix A §1 item 3; Appendix B §1 "Prefetch queue", §2 S1/S3/S6), written from the model's
// mechanisms (validation/v35s/chains/sim/queue.py) under fit 62, not ported from it.
//
// Storage is eight bytes (six nominal, eight inside a clock) in a ring, the delivered word's
// second byte counted as the ring's last entry while it waits in the one-byte write-port latch
// (`lat`, word_latch=byte_d). The decoder reads the head through a four-byte window that
// bypasses this clock's delivery (S1: delivery before take). The request rule's room is
// v35_front_pkg::room_f, evaluated at each stage that reads it from that stage's values.
//
// Stage map (all combinational from the registers and the earlier stages, written once at
// `ce_a`; no block reads its own outputs):
//   S1  arrive: the delivered word's bytes, `lat`, inflight cleared, completed (owed−1);
//       retry_after on a non-fetch cycle's end; the abort's end; room_c
//   S2  (T, the loader's pops) the retry_at countdown's raise, the take sync's `asked`
//       (twice: a deferred sync at the clock's start, a take's at its end), room_t
//   S3  (L, the IR load) room_x, the request flag, `wants_fetch`, the request's dating
//   S4  (X, the arbiter's grant) fetch issue (the reissue), the aborted cycle
//   S5  (P, the second pass's pops) a take's `asked`, io_ir_hold, nop_hold
//   S6  (E) the write-port latch (`check`), the back-to-back commitment, the next state
//
// Registered state (widths) and the model variables it replaces:
//   q 8×8, head 3, cnt 4             bytes (len(bytes) = stored + latched)
//   lat 1, lat_full 1                latched, latch_full
//   unc 3                            uncommitted (take_commit=at_end)
//   take_addr 20                     the head byte's address (modrm_mate, the trace)
//   flag 1                           flag (request_eval=on_change, request_hold=lapse)
//   rq_v 1                           requested_at is not None (dated by strobes: rq_now)
//   inflight 1, fetch_addr 20        inflight, fetch_addr
//   b2b 1                            b2b_at == t (registered at a fetch's last clock)
//   retry 1, retry_loop 1            retry, retry_loop (abort_fetch=retry, abort_unit=loop)
//   rt_v 1, rt_cnt 9                 retry_at as a countdown
//   nop_held 1, io_held 1            nop_held, io_held (their clocks: "a start since")
//   discard 1                        discard (a flush drops the word in flight)
//   starts 2                         starts (saturating at 3: `starts > 2`)
//   fhold 6, st_inf 1                str_held - t (a row's fetch_hold / fetch_release n), (S5a)
//                                    str_held = inf (fetch_release None)
//   rs_v 1, rs_cnt 4                 (S5a) str_raise - t (fetch_release n, "raise")
//   sh_held 1, sh_v 1, sh_cnt 9      shift_held, shift_until (count_latch) as a countdown
//   first 1                          t == 0 (_evaluates)
//   sfetch 1                         slot_fetch (its word: slot_word on its delivery clock)
//   (S5a) fh_v 1, fh_cnt 5           flush_held - t (flush_hold=start, flush_from)
//   ox_v 1, ox_fed 1, ox_nt 1,       odd_xfer is set (t > odd_xfer), odd_fed, odd_nt, odd_nt ==
//   ox_dbnz 1, ou_v 1, ou_cnt 3      "dbnz", odd_until - t (xfer_odd, xfer_nt)
//   od_v 1, od_nb 1, od_inf 1,       the decide row's old fetch: the fetches issued before
//   od_since 4                       nb_at (xfer_nt_b2b, nb_start == start_clock) or odd_until:
//                                    in flight, t - its end
//   xa 1                             xfer_abort (raised again at the aborted cycle's end)
//   ira 1                            io_run_at == t (xfer_nt_b2b's committed fetch)
//   th_a 1, th_on 1, th_pre 1, th_c 1  take_hold is set, hold_from is set, requested_at <
//                                    hold_from, cvt_held (bf_imm_hold, cvt_hold)
//   (S5b) pb_done 1, pr_done 1       pb_start == start_clock (page_b2b=reg: the form's one
//                                    commitment made), pr_start == start_clock (page_run's)
//
// (S5b) The 0F page's rules here: page_ir_room=end (the full-latch bit op: an empty IR is no
// seventh slot while it runs, and its steps' end evaluates the request: flag or room >= 2);
// at a fetch's last clock, after the raised flag's commitment, page_b2b=reg (_page_b2b: a 0F
// register form, its operand bytes taken, once per form, nothing latched, a byte of room, the
// fetch near the last take: its `take_near` flag, page_b2b_win=run's look-back carried from the
// fetch before it (the bus unit's), the IR not loaded before the fetch issued, the queue able
// to take the word) and page_run (_page_active: a 0F memory form's read not yet issued, once
// per form, a word of room); both commit the next fetch back to back (io_run_at).
module v35_queue
    import v35_front_pkg::*;
(
    input  wire        clock,
    input  wire        reset_n,
    input  wire        ce_a,
    input  wire        ce_b,          // (S7b) the CPU clock's second tick (the pipeline registers)
    input  wire [19:0] reset_addr,      // the first fetch's address (FFFF0h)
    input  wire [19:0] ps_base,         // (S6) {PS, 0h} after this clock: the fetch wraps at FFFFh

    // ---------------------------------------------------------------- S0/S1 from the bus
    input  wire        dlv_fetch,       // a fetch ended on t-1: its word arrives now
    input  wire        dlv_other,       // another cycle ended on t-1 (retry_after)
    input  wire [19:0] dlv_addr,
    input  wire [15:0] dlv_data,
    input  wire        abort_done,      // the aborted cycle ended on t-1
    input  wire        abort_busy,      // an aborted cycle is in flight (after S1)
    input  wire        fetch_last,      // a fetch's last clock is t (S6: the b2b decision)
    input  wire        fetch_inflight_c,  // (S5a) bus.fetch_inflight(t) (S0)
    input  wire [3:0]  fetch_since_c,     // (S5a) t - last_fetch_end (S0, sat)

    // ---------------------------------------------------------------- S2 (T) from loader, EU
    input  wire [1:0]  t_pops,          // bytes the EU took
    input  wire        t_commit,        // its take step committed
    input  wire        t_commit1,       // the ModR/M byte committed at once (modrm_commit=byte)
    input  wire        t_take,          // a take on this clock (take_t == t)
    input  wire        t_mate,          // the ModR/M's word-mate taken (modrm_mate)
    input  wire        t_disp,          // a displacement's take (latch_disp): T, P
    input  wire        p_disp,
    input  wire        t_start,         // an instruction started (start_t == t)
    input  wire        t_flush,         // a transfer's flush (the prelude's BR far)
    input  wire [19:0] t_flush_addr,
    input  wire        t_sth,           // str_held set by T (fetch_hold / fetch_release): ...
    input  wire        t_sth_inf,       //   for ever, or
    input  wire [5:0]  t_sth_n,         //   no request for n clocks from now
    input  wire        p_sth,           // ... by S5 (from the next clock)
    input  wire        p_sth_inf,
    input  wire [5:0]  p_sth_n,
    input  wire        rs_set,          // (S5a) str_raise = t + rs_n (fetch_release n, "raise")
    input  wire [3:0]  rs_n,
    input  wire        cnt_take,        // count_latch: a shift's count byte take ends now
    input  wire        sh_set,          // ... the shift's last clock is t + sh_n
    input  wire [9:0]  sh_n,
    input  wire        ask_d,           // the EU resolves a deferred take sync (imm_landed)
    input  wire        ask_t,           // the EU's take step ends with a take sync
    input  wire        rt_set,          // abort_unit=loop: retry_at = t + rt_n
    input  wire signed [9:0] rt_n,      //   (≤ 0: retry_first, raised on this clock)
    // decoder state the room reads
    input  wire [2:0]  need_c,          // before T
    input  wire        ir_v_c,
    input  wire        imm16_c,
    input  wire [2:0]  need_t,          // after T
    input  wire        ir_v_t,
    input  wire        imm16_t,
    input  wire        ir_hold,         // ir_load=disp_data: before T, after T, after S5
    input  wire        ir_hold_t,
    input  wire        ir_hold_p,
    input  wire        ir_rel,          // ... released by an EU cycle's issue (the P IR load)
    input  wire        ea_act_c,        // ea_ir_room: t < ea_end (before T, after T)
    input  wire        ea_act_x,
    input  wire        fresh_c,         // room_ir_pre=modrm: decoder.fresh (before T, after T,
    input  wire        fresh_t,         //   after S5)
    input  wire        fresh_p,
    input  wire [2:0]  xk_c,            // (S5a) the running form {lea_wait, xfer_mem, far_xfer}:
    input  wire [2:0]  xk_t,            //   before T, after T, after S5 (lea_slot, far_room,
    input  wire [2:0]  xk_p,            //   xfer_mem_room)
    input  wire        lea_xk_c,        // (S5a) lea_room=ir active: before T, after T, after S5
    input  wire        lea_xk_t,
    input  wire        lea_xk_p,

    // ---------------------------------------------------------------- S3 (L)
    input  wire        l_pop,           // the IR load
    input  wire [2:0]  need_l,

    // ---------------------------------------------------------------- S4 (X) from the arbiter
    input  wire        g_fetch,         // a fetch issued
    input  wire        g_abort,         // the aborted cycle
    input  wire        g_mem_waiting,   // request_reissue=no_mem: a memory request waits
    input  wire        abort_loop,      // abort_unit=loop: a count-loop form started now
    input  wire        rq_set_x,        // the arbiter dates the request now (free_hold)
    input  wire        g_slot_fetch,    // the fetch issued runs in a left-out write's slot
    input  wire        g_io,            // an EU I/O cycle issued (io_take=unit's drop)
    input  wire        unit_md,         // a memory multiply / divide runs (eu.unit, mul / div)

    // ---------------------------------------------------------------- S5 (P) from loader, EU
    input  wire        p_run,           // the second pass runs (an EU I/O cycle issued)
    input  wire [1:0]  p_pops,          // its take (one byte at most)
    input  wire        p_commit,
    input  wire        p_commit1,
    input  wire        p_take,
    input  wire        p_ir,            // its IR load
    input  wire        p_start,
    input  wire        ask_p,
    input  wire        ir_v_p,
    input  wire [2:0]  need_p,
    input  wire        imm16_p,
    input  wire        io_drop,         // io_take=unit: the P take's request dropped (a retry)
    input  wire        io_drop_loop,    // ... raised again at the count loop's exit
    input  wire        nop_cand,        // nop_hold: a register-only form without operand bytes
                                        // started on this clock (T)
    // (S5a) the transfers' holds (the sequencer's, at a start: T or P)
    input  wire        xs_start,        // a form started on this clock
    input  wire        fh_set,          // flush_hold=start: a taken transfer started ...
    input  wire [4:0]  fh_n,            // ... no request from its class's hold clocks on
    input  wire        ox_set,          // xfer_odd=idle: a taken short transfer at an odd address
    input  wire        nt_set,          // xfer_nt=dbnz_z: a short transfer not taken (odd, or
    input  wire        nt_dbnz,         //   DBNZE / DBNZNE); its base class is DBNZ's
    input  wire        ou_set,          // ... its clocks after the operand take: odd_until = t + ou_n
    input  wire [2:0]  ou_n,
    input  wire        xs_done,         // the running form's steps ended on this clock
    input  wire        ff_set,          // flush_from (ret_far_fetch=after): flush_held = t + ff_n
    input  wire [2:0]  ff_n,
    input  wire        ff_t,            // ... by the T pass (this clock's want) ...
    input  wire        ff_t0,           // ... with n = 0
    input  wire        ntb_ok,          // xfer_nt_b2b=decide: a conditional short transfer not
                                        // taken waits at its decide row (once per form)
    input  wire        xfer_x,          // xfer_abort=word: the running form is a transfer class
    input  wire        th_arm_t,        // (S5a) a take hold armed (bf_imm_hold, cvt_hold): T, P ...
    input  wire        th_arm_p,
    input  wire        th_cvt,          //   ... cvt_hold's (its held request no take's asked)
    input  wire        th_lift_t,       //   ... lifted or cancelled: T, P
    input  wire        th_lift_p,
    // (S5b) the 0F page
    input  wire        fl_c,            // page_ir_room=end: the full-latch bit op runs (before T,
    input  wire        fl_t,            //   after T, after S5)
    input  wire        fl_p,
    input  wire        fl_end_t,        // ... its steps ended now (T at the clock's start, T after
    input  wire        fl_end_t2,       //   a row, P): the request evaluated
    input  wire        fl_end_p,
    input  wire        pgb2b_e,         // page_b2b=reg: the last form started is a 0F register form
    input  wire        halted,          // eu.halted
    input  wire        res0_e,          // eu.resume <= t at the clock's end
    input  wire        pg_act_e,        // page_run: eu.page_active() at the clock's end
    input  wire        cf_tn,           // the fetch on the bus: take_near (its last take near it,
                                        //   or page_b2b_win=run's carried from the fetch before)
    input  wire        cf_irb,          // ... the IR held an opcode loaded no later than its issue
    input  wire        start_any,       // a form started on this clock (T or P)

    // ---------------------------------------------------------------- outputs
    output wire [7:0]  vb0, vb1, vb2, vb3, vb4, // the head window (the delivery bypassed)
    output wire [19:0] head_addr,
    output wire [3:0]  avail_c,         // bytes available to the decoder after S1
    output wire        arrived_now,     // arrived_t == t
    output wire        inflight_c,      // after S1
    output wire        inflight_x,      // after S4
    output wire        completed_now,   // a fetch (or an aborted cycle) completed: owed−1
    output wire signed [4:0] room_c,
    output wire signed [4:0] room_x,
    output wire signed [4:0] room_p0,   // after S4, before the second pass (its sync lapse)
    output wire [3:0]  stored_c,        // stored() after S1
    output wire [3:0]  stored_l,        // ... after S3
    output wire        lat_c,           // latched after S1 (imm_landed, port_landed)
    output wire        lat_x,
    output wire        asked_d,         // asked(t) for the deferred sync
    output wire        asked_t,         // ... for the T take
    output wire        asked_p,         // ... for the P take
    output wire        flag_x,          // the request flag after S3 (before the grant)
    output wire        want_x,          // wants_fetch(t)
    output wire        nb_now,          // (S5a) xfer_nt_b2b: the commitment made at this clock's end
    output wire        dec_inf,         // (S5a) the decide row's fetch (xfer_nt_b2b / xfer_nt: the
    output wire [3:0]  dec_since,       //   fetches before the commitment or odd_until): in
                                        //   flight, clocks since its end
    output wire        want_c,          // (S5a) ... as the EU's start gate sees it (before T:
                                        //   refill_start=full_io)
    output wire        rq_v_x,          // requested_at is set (after wants_fetch)
    output wire        rq_now_x,        // requested_at == t
    output wire        rq_old_c,        // requested_at < t, before S3 (io_older in T)
    output wire        rq_old_p,        // ... after S4 (io_older in P)
    output wire        rq_clr_p,        // requested_at was cleared on this clock (S4)
    output wire        b2b_now,         // b2b_at == t
    output wire        triple_x,        // queue.triple(t)
    output wire        retry_o,         // retry, retry_loop (the EU's loop row reads them)
    output wire        retry_loop_o,
    output wire [19:0] fetch_addr_o,    // the next fetch's address (a T flush's target)
    output wire        io_held_o,
    output wire        io_hold_x,       // io_ir_hold: the held request keeps no fetch (S4)
    output wire        latch_start_now, // latch_start: the byte behind a full queue went in
    output wire        nop_held_o,
    output wire        shift_latch,     // count_latch: the shift holds the queue port from now
    output wire        rq_ir_hold,      // io_ir_hold dated the request on this clock (S5)
    output wire        b2b_next,        // the S6 decision (the trace's B)
    output wire signed [4:0] room_e,
    output wire        flag_e,
    output wire        rq_v_e,          // requested_at is set at the clock's end
    output wire        io_unit_drop,    // io_take=unit: the request dropped on the I/O's issue
    output wire signed [4:0] room_c0,   // room_c with the IR counted empty (imm_start)
    output wire        overflow         // QueueOverflow (sticky)
);
    // ------------------------------------------------------------ registered state
    reg [7:0]  q [0:7];
    reg [2:0]  head = 3'd0;
    reg [3:0]  cnt = 4'd0;
    reg        lat = 1'b0;
    reg        lat_full = 1'b0;
    reg [2:0]  unc = 3'd0;
    reg [19:0] take_addr = 20'd0;
    reg        flag = 1'b0;
    reg        rq_v = 1'b0;
    reg        inflight = 1'b0;
    reg [19:0] fetch_addr = 20'd0;
    reg        b2b = 1'b0;
    reg        retry = 1'b0;
    reg        retry_loop = 1'b0;
    reg        rt_v = 1'b0;
    reg [8:0]  rt_cnt = 9'd0;
    reg        nop_held = 1'b0;
    reg        io_held = 1'b0;
    reg        discard = 1'b0;
    reg [1:0]  starts = 2'd0;
    reg [5:0]  fhold = 6'd0;
    reg        st_inf = 1'b0;
    reg        rs_v = 1'b0;
    reg [3:0]  rs_cnt = 4'd0;
    reg        sh_held = 1'b0;
    reg        sh_v = 1'b0;
    reg [8:0]  sh_cnt = 9'd0;
    reg        first = 1'b1;
    reg        ovf = 1'b0;
    reg        sfetch = 1'b0;           // slot_fetch: the fetch in flight runs in a slot
    // (S5a) the transfers' holds
    reg        fh_v = 1'b0;             // flush_held is set ...
    reg [4:0]  fh_cnt = 5'd0;           // ... flush_held - t (0: from here on)
    reg        ox_v = 1'b0;             // odd_xfer is set (and t > odd_xfer)
    reg        ox_fed = 1'b0;           // odd_fed: a fetch was on the bus on the start clock
    reg        ox_nt = 1'b0;            // odd_nt (a not-taken transfer's hold) ...
    reg        ox_dbnz = 1'b0;          // ... of the loop format's base class (odd_nt == "dbnz")
    reg        ou_v = 1'b0;             // odd_until is set ...
    reg [2:0]  ou_cnt = 3'd0;           // ... odd_until - t (0: reached)
    reg        od_v = 1'b0;             // the decide's old fetch is tracked (nb_at / odd_until) ...
    reg        od_nb = 1'b0;            // ... from the xfer_nt_b2b commitment
    reg        od_inf = 1'b0;           // ... it is in flight
    reg [3:0]  od_since = 4'd0;         // ... clocks since its end
    reg        xa = 1'b0;               // xfer_abort: raise the request at the aborted cycle's end
    reg        ira = 1'b0;              // io_run_at == t (xfer_nt_b2b's committed fetch: requested)
    reg        th_a = 1'b0;             // take_hold is set (armed) ...
    reg        th_on = 1'b0;            // ... hold_from is set (the first take after it)
    reg        th_pre = 1'b0;           // ... a request raised before hold_from still stands
    reg        th_c = 1'b0;             // ... cvt_held
    reg        pb_done = 1'b0;          // (S5b) page_b2b's commitment made for the running form
    reg        pr_done = 1'b0;          // (S5b) page_run's

    integer i;
    initial for (i = 0; i < 8; i = i + 1) q[i] = 8'h00;

    // ------------------------------------------------------------ S1: arrival
    wire       arrive = dlv_fetch && !discard;
    wire [1:0] n_arr = !arrive ? 2'd0 : (dlv_addr[0] ? 2'd1 : 2'd2);
    wire [7:0] a0 = dlv_addr[0] ? dlv_data[15:8] : dlv_data[7:0];
    wire [7:0] a1 = dlv_data[15:8];
    assign arrived_now = arrive;
    assign completed_now = dlv_fetch || abort_done;
    assign inflight_c = inflight && !dlv_fetch && !abort_done;
    wire [3:0] cnt_c = cnt + 4'(n_arr);
    assign avail_c = cnt_c;
    wire lat_c_w = arrive ? 1'b1 : lat;
    assign lat_c = lat_c_w;

    // the head window: ring bytes, then this clock's delivery
    function automatic logic [7:0] vbyte(input logic [2:0] k);
        logic [3:0] kk;
        kk = {1'b0, k};
        if (kk < cnt)
            vbyte = q[head + k];
        else if (kk == cnt)
            vbyte = a0;
        else
            vbyte = a1;
    endfunction
    assign vb0 = vbyte(3'd0);
    assign vb1 = vbyte(3'd1);
    assign vb2 = vbyte(3'd2);
    assign vb3 = vbyte(3'd3);
    assign vb4 = vbyte(3'd4);
    assign head_addr = take_addr;

    // removal and port strobes, per stage (removed_t, qport_t, ir_t == t)
    wire [2:0] unc_pre_t = unc + 3'(t_pops) - (t_commit1 ? 3'd1 : 3'd0);
    wire qport_t = t_commit && unc_pre_t != 3'd0;
    wire rem_t = qport_t || t_commit1 || t_flush;
    wire rem_l = rem_t || l_pop;
    wire qport_l = qport_t || l_pop;
    wire [2:0] unc_l_w = l_pop ? 3'd0 : (t_flush ? 3'd0 : (t_commit ? 3'd0 : unc_pre_t));
    wire [2:0] unc_t_w = t_flush ? 3'd0 : (t_commit ? 3'd0 : unc_pre_t);
    wire ir_now_l = l_pop;

    // counts after each stage (a flush empties the queue in T)
    wire [3:0] cnt_t = t_flush ? 4'd0 : cnt_c - 4'(t_pops);
    wire [3:0] cnt_l = cnt_t - (l_pop ? 4'd1 : 4'd0);
    // latched = min(latched, len(bytes)): a byte taken through the latch
    wire lat_t_w = lat_c_w && cnt_t != 4'd0 && !t_flush;
    wire lat_l = lat_t_w && cnt_l != 4'd0;
    assign lat_x = lat_l;

    // _port_busy (latch_read=commit, modrm_port): the decoder holds the write port
    wire pb_c = 1'b0;
    wire pb_t = arrive ? rem_t : qport_t;
    wire pb_l = arrive ? rem_l : (qport_l || ir_now_l);
    // the clock is one the request flag is evaluated on (_evaluates, request_eval=on_change)
    // (room_ir_pre: the start of a TEST r,r / INC-DEC r8 emptied the IR, the room)
    wire ev_c = arrive || first;
    wire ev_t = ev_c || rem_t || (t_start && fresh_t);
    wire ev_l = ev_t || rem_l;

    // the rooms
    wire inflight_x_w = inflight_c || g_fetch || g_abort;
    wire sw = arrive && sfetch;
    assign room_c = room_f(cnt_c, unc, inflight_c, lat_c_w, arrive, pb_c, need_c,
                           1'b0, ir_v_c, imm16_c, ir_hold, 1'b0, ea_act_c, fresh_c, sw, xk_c, lea_xk_c,
                           fl_c);
    assign room_c0 = room_f(cnt_c, unc, inflight_c, lat_c_w, arrive, pb_c, need_c,
                            1'b0, 1'b0, imm16_c, ir_hold, 1'b0, ea_act_c, fresh_c, sw, xk_c, lea_xk_c,
                            fl_c);
    // (S5b) page_ir_room=end: the room as the full-latch bit op's end leaves it (its slot back)
    wire signed [4:0] room_cf = room_f(cnt_c, unc, inflight_c, lat_c_w, arrive, pb_c, need_c,
                                       1'b0, ir_v_c, imm16_c, ir_hold, 1'b0, ea_act_c, fresh_c,
                                       sw, xk_c, lea_xk_c, 1'b0);
    wire signed [4:0] room_t = room_f(cnt_t, unc_t_w, inflight_c, lat_t_w, arrive,
                                      pb_t, need_t, t_disp, ir_v_t, imm16_t, ir_hold_t,
                                      t_mate, ea_act_x, fresh_t, sw, xk_t, lea_xk_t, fl_t);
    // count_latch: a register shift's operand take (an immediate count) on a word's delivery
    // clock with its second byte latched and no room for a word but that uncounted byte: no
    // fetch until the shift's last clock (queue.shift_held)
    wire signed [4:0] room_cl = room_t - ((lat_t_w && need_t == 3'd0) ? 5'sd1 : 5'sd0);
    wire sh_latch = cnt_take && arrive && lat_t_w && room_cl < 5'sd2;
    assign room_x = room_f(cnt_l, unc_l_w, inflight_c, lat_l, arrive, pb_l,
                           need_l, t_disp, ir_v_t || l_pop, imm16_t, ir_hold_t, t_mate,
                           ea_act_x, fresh_t, sw, xk_t, lea_xk_t, fl_t);
    // after the grant (the reissue reads it with the word in flight)
    wire signed [4:0] room_g = room_f(cnt_l, unc_l_w, 1'b1, lat_l, arrive, pb_l,
                                      need_l, t_disp, l_pop || ir_v_t, imm16_t,
                                      ir_hold_t, t_mate, ea_act_x, fresh_t, sw, xk_t, lea_xk_t,
                                      fl_t);
    assign room_p0 = room_f(cnt_l, unc_l_w, inflight_x_w, lat_l, arrive, pb_l, need_l,
                            t_disp, l_pop || ir_v_t, imm16_t, ir_hold_t, t_mate, ea_act_x,
                            fresh_t, sw, xk_t, lea_xk_t, fl_t);

    // stored() = len(bytes) - latched
    assign stored_c = cnt_c - (lat_c_w ? 4'd1 : 4'd0);
    assign stored_l = cnt_l - (lat_l ? 4'd1 : 4'd0);

    // ------------------------------------------------------------ the request flag
    // S1: retry_after (a non-fetch cycle ended on t-1)
    wire retry_c = dlv_other && retry && !retry_loop;
    // xfer_abort=word: a transfer's aborted cycle raises the request again at its end
    wire flag_ca = (abort_done && xa) ? room_c >= 5'sd2 : flag;
    wire flag_c = retry_c ? room_c >= 5'sd2 : flag_ca;
    wire retry_c1 = retry_c ? 1'b0 : retry;
    // S2 start: retry_at reached (abort_unit=loop's count-loop exit)
    // S2 start: shift_until reached (count_latch: the shift's last clock passed), then
    // retry_at (abort_unit=loop's count-loop exit); each raises the request again
    wire sh_fire = sh_v && sh_cnt == 9'd0;
    wire flag_s = sh_fire ? room_c >= 5'sd2 : flag_c;
    wire rt_fire = rt_v && rt_cnt == 9'd0;
    wire rt_raise = rt_fire && retry_c1;
    wire flag_t0 = rt_raise ? room_c >= 5'sd2 : flag_s;
    wire retry_t0 = rt_raise ? 1'b0 : retry_c1;
    // (S5b) page_ir_room=end: the full-latch bit op's steps ended (T): the empty IR is room
    // again, the request evaluated on this clock (raised, or room for a word)
    wire flag_fl = fl_end_t ? (flag_t0 || room_cf >= 5'sd2) : flag_t0;
    // retry_first: the loop row's retry_at at or before t raises on this clock
    wire rt_now = rt_set && rt_n <= 10'sd0;
    // asked(t) (take_sync=pending): requesting(t) when no word is in flight
    wire want_d = ira || (ev_c ? room_c >= 5'sd2 : flag_fl && room_c >= 5'sd2);
    // (S5a) wants_fetch(t) before T's takes (eu._start's refill_start=full_io test)
    assign want_c = want_d && !inflight_c && fhold == 6'd0 && !st_inf && !nop_held
                    && !(lat_c_w && !arrive && cnt_c > 4'(QUEUE_BYTES)) && !(sh_held && !sh_fire);
    // (S5a) the take hold (queue._take_held): from the first operand take after it was armed
    // (that clock included) no request is raised but one raised before that take
    wire th_arm_c = (th_a || th_arm_t) && !th_lift_t;
    wire th_on_t = th_on ? !th_lift_t : (th_arm_c && t_take);
    wire th_pre_t = th_on ? th_pre : rq_v;
    wire th_held = th_on_t && !th_pre_t;
    // (S5a) xfer_odd / xfer_nt: no request (nor a take's asked) from the clock after an odd
    // short transfer's start once its operand bytes are taken (a taken one: unless a fetch was
    // on the bus on its start clock; to odd_until when it was not taken)
    function automatic logic odd_held(input logic [2:0] nd, input logic fl);
        odd_held = ox_v && !fl && nd == 3'd0 && (ox_dbnz || !ox_fed)
                   && !(ou_v && ou_cnt == 3'd0);
    endfunction
    assign asked_d = inflight_c ? room_c >= 5'sd2 : want_d && !odd_held(need_c, 1'b0);
    wire flag_d0 = (ask_d && !inflight_c) ? want_d : flag_fl;
    // ... (the steps' end after a row of this clock: after the deferred sync's asked)
    wire flag_d = fl_end_t2 ? (flag_d0 || room_cf >= 5'sd2) : flag_d0;
    wire flag_r = (rt_now && retry_t0) ? room_t >= 5'sd2 : flag_d;
    wire retry_t1 = (rt_now && retry_t0) ? 1'b0 : retry_t0;
    wire want_tk = ira || (ev_t ? room_t >= 5'sd2 : flag_r && room_t >= 5'sd2);
    wire flag_t = t_flush ? 1'b0 : ((ask_t && !inflight_c) ? want_tk : flag_r);

    // S3: requesting(t) in wants_fetch
    // (S5a) str_raise (str_fetch=hold, CW = 0): the request an aborted start left raised again
    wire rs_fire = rs_v && rs_cnt == 4'd0;
    wire flag_rs = (rs_fire && retry_t1) ? room_x >= 5'sd2 : flag_t;
    wire raw_x = ira || (ev_l ? room_x >= 5'sd2 : flag_rs && room_x >= 5'sd2);
    assign flag_x = raw_x;
    wire nop_act_x = nop_held && !t_start;
    wire fhold_act = t_sth ? (t_sth_inf || t_sth_n != 6'd0) : (st_inf || fhold != 6'd0);
    wire latch_blocks = lat_l && !arrive && (pb_l || cnt_l > 4'(QUEUE_BYTES));
    wire sh_held_t = (sh_held && !sh_fire) || sh_latch;
    // flush_hold=start: a taken transfer's request held from its class's hold clocks after its
    // start to its flush, once its operand bytes are taken (and from flush_from's clock on)
    // (every transfer class's hold is 1 or more: a start's own clock is never held)
    wire fh_act = (ff_t ? ff_t0 : (fh_v && fh_cnt == 5'd0)) && need_l == 3'd0 && !t_flush;
    wire want_w = raw_x && !fhold_act && !nop_act_x && !inflight_c && !latch_blocks
                  && !fh_act && !odd_held(need_l, t_flush) && !th_held
                  && !sh_held_t;
    assign want_x = want_w;
    wire rq_after_want = want_w ? 1'b1 : (inflight_c ? (rq_v && !t_flush) : 1'b0);
    // (as wants_fetch leaves it, before the arbiter's re-dating: the arbiter reads these)
    assign rq_now_x = want_w && !(rq_v && !t_flush);
    assign rq_v_x = rq_after_want;
    assign rq_old_c = rq_v;
    // S4: the grant
    wire flag_g = g_fetch ? (!g_mem_waiting && ev_l ? room_g >= 5'sd2 : 1'b0)
                          : (g_abort ? 1'b0 : flag_x);
    wire rq_g = (g_fetch || g_abort) ? 1'b0 : rq_v_x;
    assign inflight_x = inflight_x_w;
    assign rq_old_p = rq_g && !rq_now_x && !rq_set_x;
    assign rq_clr_p = rq_v && !rq_g;

    // ------------------------------------------------------------ (S7b) the ce_b registers
    // Tick A (S1-S4: arrival, the T pass's takes, the IR load, the request, the grant) ends at
    // ce_b; tick B (S5, S6: the P pass's takes, the check, b2b, the next state) reads its
    // results from these registers (and the architectural registers), never tick A's logic.
    reg  [2:0]  unc_l_w_b = 3'd0, need_t_b = 3'd0;
    reg         qport_l_b = 1'b0, rem_l_b = 1'b0, l_pop_b = 1'b0, lat_l_b = 1'b0, ev_l_b = 1'b0;
    reg  [3:0]  cnt_l_b = 4'd0;
    reg         inflight_x_w_b = 1'b0, t_disp_b = 1'b0, t_mate_b = 1'b0, ea_act_x_b = 1'b0;
    reg         sw_b = 1'b0, flag_g_b = 1'b0, t_flush_b = 1'b0, g_io_b = 1'b0, p_run_b = 1'b0;
    reg         t_take_b = 1'b0, retry_t1_b = 1'b0, rq_g_b = 1'b0, g_fetch_b = 1'b0;
    reg         g_abort_b = 1'b0, nop_cand_b = 1'b0, ir_now_l_b = 1'b0, t_start_b = 1'b0;
    reg  [19:0] t_flush_addr_b = 20'd0, ps_base_b = 20'd0;
    reg  [1:0]  t_pops_b = 2'd0;
    reg         th_lift_t_b = 1'b0, th_arm_t_b = 1'b0, th_on_t_b = 1'b0, th_arm_c_b = 1'b0;
    reg         th_pre_t_b = 1'b0, th_held_b = 1'b0, xfer_x_b = 1'b0, g_slot_fetch_b = 1'b0;
    reg         abort_loop_b = 1'b0, rs_fire_b = 1'b0, rt_set_b = 1'b0, rt_now_b = 1'b0;
    reg  signed [9:0] rt_n_b = 10'sd0;
    reg         rt_fire_b = 1'b0, flag_x_b = 1'b0, inflight_c_b = 1'b0, t_sth_b = 1'b0;
    reg         t_sth_inf_b = 1'b0, sh_held_t_b = 1'b0, sh_set_b = 1'b0, sh_fire_b = 1'b0;
    reg  [5:0]  t_sth_n_b = 6'd0;
    reg  [9:0]  sh_n_b = 10'd0;
    reg  signed [4:0] room_t_b = 5'sd0;
    reg         want_tk_b = 1'b0;
    always @(posedge clock) begin
        if (ce_b) begin
            unc_l_w_b <= unc_l_w;
            need_t_b <= need_t;
            qport_l_b <= qport_l;
            rem_l_b <= rem_l;
            l_pop_b <= l_pop;
            lat_l_b <= lat_l;
            ev_l_b <= ev_l;
            cnt_l_b <= cnt_l;
            inflight_x_w_b <= inflight_x_w;
            t_disp_b <= t_disp;
            t_mate_b <= t_mate;
            ea_act_x_b <= ea_act_x;
            sw_b <= sw;
            flag_g_b <= flag_g;
            t_flush_b <= t_flush;
            g_io_b <= g_io;
            p_run_b <= p_run;
            t_take_b <= t_take;
            retry_t1_b <= retry_t1;
            rq_g_b <= rq_g;
            g_fetch_b <= g_fetch;
            g_abort_b <= g_abort;
            nop_cand_b <= nop_cand;
            ir_now_l_b <= ir_now_l;
            t_start_b <= t_start;
            t_flush_addr_b <= t_flush_addr;
            ps_base_b <= ps_base;
            t_pops_b <= t_pops;
            th_lift_t_b <= th_lift_t;
            th_arm_t_b <= th_arm_t;
            th_on_t_b <= th_on_t;
            th_arm_c_b <= th_arm_c;
            th_pre_t_b <= th_pre_t;
            th_held_b <= th_held;
            xfer_x_b <= xfer_x;
            g_slot_fetch_b <= g_slot_fetch;
            abort_loop_b <= abort_loop;
            rs_fire_b <= rs_fire;
            rt_set_b <= rt_set;
            rt_now_b <= rt_now;
            rt_n_b <= rt_n;
            rt_fire_b <= rt_fire;
            flag_x_b <= flag_x;
            inflight_c_b <= inflight_c;
            t_sth_b <= t_sth;
            t_sth_inf_b <= t_sth_inf;
            t_sth_n_b <= t_sth_n;
            sh_held_t_b <= sh_held_t;
            sh_set_b <= sh_set;
            sh_fire_b <= sh_fire;
            sh_n_b <= sh_n;
            room_t_b <= room_t;
            want_tk_b <= want_tk;
        end
    end

    // ------------------------------------------------------------ (S7b) tick B
    // (S7b) asked(t) of the T take: in tick B (the take hold's cvt flag may be the P pass's)
    assign asked_t = inflight_c_b ? room_t_b >= 5'sd2 : want_tk_b && !odd_held(need_t_b, 1'b0)
                                                        && !(th_held_b && (th_c || th_cvt));
    wire [2:0] unc_pre_p = unc_l_w_b + 3'(p_pops) - (p_commit1 ? 3'd1 : 3'd0);
    wire qport_pp = p_commit && unc_pre_p != 3'd0;
    wire rem_p = rem_l_b || qport_pp || p_commit1 || p_ir;
    wire qport_p = qport_l_b || qport_pp || p_ir;
    wire [2:0] unc_p_w = p_ir ? 3'd0 : (p_commit ? 3'd0 : unc_pre_p);
    wire ir_now_p = l_pop_b || p_ir;
    wire [3:0] cnt_p = cnt_l_b - 4'(p_pops) - (p_ir ? 4'd1 : 4'd0);
    wire lat_p = lat_l_b && cnt_p != 4'd0;
    wire pb_p = arrive ? rem_p : (qport_p || ir_now_p);
    wire ev_p = ev_l_b || rem_p || (p_start && fresh_p);
    wire signed [4:0] room_pp = room_f(cnt_p, unc_p_w, inflight_x_w_b, lat_p, arrive, pb_p,
                                       need_p, t_disp_b || p_disp, ir_v_p, imm16_p,
                                       ir_hold_p, t_mate_b, ea_act_x_b, fresh_p, sw_b, xk_p, lea_xk_p,
                                       fl_p);
    // S5: a take's asked(t), then io_ir_hold (machine.py:189-195)
    // (S5b) page_ir_room=end: the full-latch bit op's end in the P pass
    wire flag_gf = fl_end_p ? (flag_g_b || room_pp >= 5'sd2) : flag_g_b;
    wire want_pt = ira || (ev_p ? room_pp >= 5'sd2 : flag_gf && room_pp >= 5'sd2);
    assign asked_p = inflight_x_w_b ? room_pp >= 5'sd2 : want_pt && !odd_held(need_p, t_flush_b);
    // io_take=unit (eu._io_drop): the request this clock raises dropped as an aborted cycle's
    wire flag_pa = io_drop ? 1'b0 : ((ask_p && !inflight_x_w_b) ? want_pt : flag_gf);
    wire want_pi = ira || (ev_p ? room_pp >= 5'sd2 : flag_pa && room_pp >= 5'sd2);
    wire iih = p_run_b && !flag_g_b && ir_now_p && !(t_take_b || p_take) && !inflight_x_w_b;
    // ir_load=disp_data: the IR loaded again on the EU cycle's issue: a queue change
    // (machine.py:185-189)
    wire flag_ir = (ir_rel && p_ir) ? room_pp >= 5'sd2 : flag_pa;
    // io_take=unit (machine.py:201-211): a request first raised on an I/O cycle's issue clock
    // by a word's delivery (its second byte latched) while a memory multiply or divide runs:
    // dropped, raised again at its loop's exit
    wire iud = g_io_b && flag_ir && arrive && lat_p && unit_md && !inflight_x_w_b && !retry_t1_b;
    assign io_unit_drop = iud;
    wire flag_p = iih ? want_pi : (iud ? 1'b0 : flag_ir);
    wire iih_set = iih && want_pi;
    assign rq_ir_hold = iih_set;
    wire rq_p = iih_set ? 1'b1 : ((io_drop || iud) ? 1'b0 : rq_g_b);
    assign rq_v_e = rq_p;
    // nop_hold=any (machine.py:206-216): on a fetch's issue clock where a register-only form
    // without operand bytes started, the IR loaded and the reissue kept the flag raised
    wire nop_set = g_fetch_b && nop_cand_b && flag_g_b && ir_now_l_b && !t_take_b;

    // ------------------------------------------------------------ S6: check, b2b
    wire latch_in = lat_p && cnt_p <= 4'(QUEUE_BYTES) && !pb_p;
    wire lat_e = lat_p && !latch_in;
    wire lat_full_e = lat_e ? (cnt_p > 4'(QUEUE_BYTES) ? 1'b1 : lat_full) : 1'b0;
    // _raised(t) on a fetch's last clock: the flag as it stands, the room after every stage
    assign room_e = room_pp;
    assign flag_e = flag_p;
    wire nop_act_e = (nop_held && !(t_start_b || p_start)) || nop_set;
    wire raised_e = !nop_act_e && (ev_p ? room_pp >= 5'sd2 : flag_p && room_pp >= 5'sd2);
    // xfer_nt_b2b=decide (queue._nt_b2b): on a fetch's last clock not committed otherwise, a
    // conditional short transfer not taken waiting at its decide row commits one more fetch
    // with a byte of room (the latch takes the word's other byte), nothing latched, the queue
    // able to hold the word
    // (S5b) page_b2b=reg (queue._page_b2b): a 0F register form, its operand bytes taken, once
    // per form, nothing latched, a byte of room; the fetch ending now ran at (or was issued the
    // clock after) its last take, or page_b2b_win=run: followed back to back a fetch that took
    // it after its issue clock (cf_tn); the IR not loaded before the fetch issued; the queue
    // able to take the word unless the IR is empty and the form's clocks are done
    wire pb_eff = pb_done && !start_any;
    wire pr_eff = pr_done && !start_any;
    wire pgb_go = fetch_last && !raised_e && pgb2b_e && !halted && need_p == 3'd0 && !pb_eff
                  && !lat_e && room_pp >= 5'sd1 && (cf_tn || t_take_b || p_take)
                  && !(ir_v_p && !t_flush_b && cf_irb && !start_any)
                  && !(stored_e + 4'd4 > 4'(QUEUE_BYTES) + 4'd1 && !(!(ir_v_p && !t_flush_b) && res0_e));
    // page_run (end_clock): a 0F memory form (or a bit field) whose read has not issued
    // commits one fetch back to back on a fetch's last clock with a word of room, once per form
    wire prun_go = fetch_last && !raised_e && !pgb_go && pg_act_e && room_pp >= 5'sd2 && !pr_eff;
    wire nb_go = fetch_last && !raised_e && !pgb_go && !prun_go && ntb_ok && !od_nb
                 && need_p == 3'd0 && !lat_e
                 && room_pp >= 5'sd1 && stored_e + 4'd4 <= 4'(QUEUE_BYTES) + 4'd1;
    assign nb_now = nb_go;
    assign b2b_next = fetch_last && (raised_e || pgb_go || prun_go || nb_go);
    // the decide row's old fetch: from odd_until on (or the commitment), only the fetches issued
    // before it count (eu.py: the decide step)
    wire ou_hit = ou_v && ou_cnt == 3'd0 && !od_v;
    wire od_inf_c = ou_hit ? fetch_inflight_c : od_inf;
    wire [3:0] od_since_c = ou_hit ? fetch_since_c : od_since;
    assign dec_inf = (od_v || ou_hit) ? od_inf_c : fetch_inflight_c;
    assign dec_since = (od_v || ou_hit) ? od_since_c : fetch_since_c;
    assign b2b_now = b2b;
    assign triple_x = t_start && t_take && l_pop && starts >= 2'd2;   // (tick A: S4)
    assign retry_o = retry_t0;      // before this clock's loop row (it reads it)
    assign retry_loop_o = retry_loop;
    assign fetch_addr_o = t_flush ? t_flush_addr : fetch_addr;   // (tick A: the grant)
    assign io_held_o = io_held;
    assign io_hold_x = io_held && !t_start && flag_x && !inflight_c;   // (tick A: S4)
    assign latch_start_now = latch_in && lat_full;
    assign shift_latch = sh_latch;
    assign nop_held_o = nop_held;
    assign overflow = ovf;

    // ------------------------------------------------------------ next state
    wire [2:0] pops = 3'(t_pops_b) + (l_pop_b ? 3'd1 : 3'd0) + 3'(p_pops) + (p_ir ? 3'd1 : 3'd0);
    wire [3:0] stored_e = cnt_p - (lat_e ? 4'd1 : 4'd0);
    wire [19:0] issue_addr = t_flush_b ? t_flush_addr_b : fetch_addr;
    always @(posedge clock) begin
        if (!reset_n) begin
            head <= 3'd0;
            cnt <= 4'd0;
            lat <= 1'b0;
            lat_full <= 1'b0;
            unc <= 3'd0;
            take_addr <= reset_addr;
            flag <= 1'b0;
            rq_v <= 1'b0;
            inflight <= 1'b0;
            fetch_addr <= reset_addr;
            b2b <= 1'b0;
            retry <= 1'b0;
            retry_loop <= 1'b0;
            rt_v <= 1'b0;
            rt_cnt <= 9'd0;
            nop_held <= 1'b0;
            io_held <= 1'b0;
            discard <= 1'b0;
            starts <= 2'd0;
            fhold <= 6'd0;
            st_inf <= 1'b0;
            rs_v <= 1'b0;
            rs_cnt <= 4'd0;
            sh_held <= 1'b0;
            sh_v <= 1'b0;
            sh_cnt <= 9'd0;
            first <= 1'b1;
            ovf <= 1'b0;
            sfetch <= 1'b0;
            // (S7b) the reset complete (S6: a take hold left on by a reset held every fetch)
            fh_v <= 1'b0;
            fh_cnt <= 5'd0;
            ox_v <= 1'b0;
            ox_fed <= 1'b0;
            ox_nt <= 1'b0;
            ox_dbnz <= 1'b0;
            ou_v <= 1'b0;
            ou_cnt <= 3'd0;
            od_v <= 1'b0;
            od_nb <= 1'b0;
            od_inf <= 1'b0;
            od_since <= 4'd0;
            xa <= 1'b0;
            ira <= 1'b0;
            th_a <= 1'b0;
            th_on <= 1'b0;
            th_pre <= 1'b0;
            th_c <= 1'b0;
            pb_done <= 1'b0;
            pr_done <= 1'b0;
        end else if (ce_a) begin
            first <= 1'b0;
            // (S5a) the transfers' holds
            if (t_flush_b) begin
                fh_v <= 1'b0;
                ox_v <= 1'b0;
                ox_nt <= 1'b0;
                ou_v <= 1'b0;
            end else begin
                if (fh_set) begin
                    fh_v <= 1'b1;
                    fh_cnt <= fh_n == 5'd0 ? 5'd0 : fh_n - 5'd1;
                end else if (ff_set) begin
                    fh_v <= 1'b1;
                    fh_cnt <= ff_n == 3'd0 ? 5'd0 : 5'(ff_n) - 5'd1;
                end else if (fh_v && fh_cnt != 5'd0)
                    fh_cnt <= fh_cnt - 5'd1;
                if (xs_start) begin
                    // a taken odd short transfer arms its hold; a successor's start ends a
                    // not-taken one's (both, as eu._start orders them); a not-taken one arms its
                    if ((ox_set && !ox_nt) || nt_set) begin
                        ox_v <= 1'b1;
                        ox_fed <= fetch_inflight_c || g_fetch_b;
                    end else if (ox_nt)
                        ox_v <= 1'b0;
                    ox_nt <= nt_set;
                    ox_dbnz <= nt_set && nt_dbnz;
                    ou_v <= nt_set && ou_set;
                    ou_cnt <= ou_n == 3'd0 ? 3'd0 : ou_n - 3'd1;
                end else if (xs_done && ox_nt) begin
                    ox_v <= 1'b0;
                    ox_nt <= 1'b0;
                    ou_v <= 1'b0;
                end else if (ou_set && ox_nt && !ou_v) begin
                    ou_v <= 1'b1;
                    ou_cnt <= ou_n == 3'd0 ? 3'd0 : ou_n - 3'd1;
                end else if (ou_v && ou_cnt != 3'd0)
                    ou_cnt <= ou_cnt - 3'd1;
            end
            // the decide row's old fetch (cleared at a start)
            if (xs_start) begin
                od_v <= 1'b0;
                od_nb <= 1'b0;
            end else if (nb_go) begin
                od_v <= 1'b1;
                od_nb <= 1'b1;
                od_inf <= 1'b0;
                od_since <= 4'd1;
            end else if (od_v || ou_hit) begin
                od_v <= 1'b1;
                od_inf <= od_inf_c && !fetch_last;
                od_since <= od_inf_c ? (fetch_last ? 4'd1 : 4'd0)
                                     : (od_since_c == 4'd15 ? 4'd15 : od_since_c + 4'd1);
            end
            ira <= nb_go || pgb_go || prun_go;
            // (S5b) the 0F page's once-per-form commitments
            pb_done <= pb_eff || pgb_go;
            pr_done <= pr_eff || prun_go || (fetch_last && raised_e && pg_act_e);
            // the take hold
            if (th_lift_p || (th_lift_t_b && !th_arm_p)) begin
                th_a <= 1'b0;
                th_on <= 1'b0;
            end else begin
                if (th_arm_t_b || th_arm_p) begin
                    th_a <= 1'b1;
                    th_c <= th_cvt;
                end
                if (th_on_t_b)
                    th_on <= 1'b1;
                else if ((th_arm_c_b || th_arm_p) && p_take)
                    th_on <= 1'b1;
            end
            th_pre <= (th_on_t_b ? th_pre_t_b : rq_v) && rq_v_e && !(g_fetch_b || g_abort_b);
            if (g_abort_b)
                xa <= xfer_x_b;
            else if (abort_done)
                xa <= 1'b0;
            if (g_slot_fetch_b)
                sfetch <= 1'b1;
            else if (dlv_fetch)
                sfetch <= 1'b0;
            // storage: the delivered bytes behind the ones held, the pops from the head
            if (t_flush_b) begin
                // a flush in T: the queue emptied before this clock's later stages
                head <= 3'd0;
                cnt <= cnt_p;
                take_addr <= t_flush_addr_b + 20'(pops) - 20'(t_pops_b);
            end else begin
                if (n_arr != 2'd0)
                    q[head + 3'(cnt)] <= a0;
                if (n_arr == 2'd2)
                    q[head + 3'(cnt) + 3'd1] <= a1;
                head <= head + pops;
                cnt <= cnt_p;
                take_addr <= take_addr + 20'(pops);
            end
            lat <= lat_e;
            lat_full <= lat_full_e;
            unc <= unc_p_w;
            if (arrive && lat)
                ovf <= 1'b1;                // a word delivered into a full latch
            if (stored_e > 4'(QUEUE_BYTES))
                ovf <= 1'b1;                // check(): more than six bytes stored
            flag <= flag_p;
            rq_v <= rq_p;
            inflight <= inflight_x_w_b;
            if (dlv_fetch)
                discard <= 1'b0;
            if (t_flush_b)
                discard <= inflight_c_b && !abort_busy;
            if (g_fetch_b)        // ((S6) the next word's offset in PS, FFFFh + 1 wrapping to 0)
                fetch_addr <= ps_base_b + {4'd0, 16'((issue_addr | 20'd1) + 20'd1 - ps_base_b)};
            else if (t_flush_b)
                fetch_addr <= t_flush_addr_b;
            b2b <= b2b_next;
            // abort_fetch=retry
            if (g_abort_b) begin
                retry <= 1'b1;
                retry_loop <= abort_loop_b;
            end else if (io_drop) begin
                retry <= 1'b1;              // io_take: raised again as an aborted cycle's
                retry_loop <= io_drop_loop;
            end else if (iud) begin
                retry <= 1'b1;
                retry_loop <= 1'b1;
            end else
                retry <= retry_t1_b && !rs_fire_b;
            if (rt_set_b && !rt_now_b) begin
                rt_v <= 1'b1;
                rt_cnt <= 9'(rt_n_b - 10'sd1);
            end else if (rt_fire_b || rt_now_b) begin
                rt_v <= 1'b0;
            end else if (rt_v)
                rt_cnt <= rt_cnt - 9'd1;
            // the holds, released by a later start
            if (nop_set)
                nop_held <= 1'b1;
            else if (t_start_b || p_start)
                nop_held <= 1'b0;
            if (iih_set)
                io_held <= 1'b1;
            else if (io_held && (t_start_b || p_start || !flag_x_b || inflight_c_b))
                io_held <= 1'b0;
            if ((t_start_b || p_start) && starts != 2'd3)
                starts <= starts + 2'd1;
            // str_held (the P pass's setting after T's)
            if (p_sth) begin
                st_inf <= p_sth_inf;
                fhold <= (p_sth_inf || p_sth_n == 6'd0) ? 6'd0 : p_sth_n - 6'd1;
            end else if (t_sth_b) begin
                st_inf <= t_sth_inf_b;
                fhold <= (t_sth_inf_b || t_sth_n_b == 6'd0) ? 6'd0 : t_sth_n_b - 6'd1;
            end else if (fhold != 6'd0)
                fhold <= fhold - 6'd1;
            // str_raise: counted down to its clock (wants_fetch raises a retried request there)
            if (rs_set) begin
                rs_v <= 1'b1;
                rs_cnt <= rs_n == 4'd0 ? 4'd0 : rs_n - 4'd1;
            end else if (rs_fire_b)
                rs_v <= 1'b0;
            else if (rs_v && rs_cnt != 4'd0)
                rs_cnt <= rs_cnt - 4'd1;
            // count_latch: held from the count's take to the shift's last clock
            sh_held <= sh_held_t_b;
            if (sh_set_b) begin
                sh_v <= 1'b1;
                sh_cnt <= sh_n_b == 10'd0 ? 9'd0 : 9'(sh_n_b - 10'd1);
            end else if (sh_fire_b) begin
                sh_v <= 1'b0;
            end else if (sh_v) begin
                sh_cnt <= sh_cnt - 9'd1;
            end
        end
    end

    // (S7b) chk begin (generated: the ce_b registers against their sources at ce_a)
`ifndef SYNTHESIS
    /* verilator lint_off BLKSEQ */
    reg chk_on = 1'b0;
    integer chk_n = 0;
    initial chk_on = $test$plusargs("v35_chk");
    always @(posedge clock) begin
        if (chk_on && reset_n && ce_a) begin
            if (unc_l_w_b !== unc_l_w) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.unc_l_w changed in tick B: %h -> %h at %0t",
                             unc_l_w_b, unc_l_w, $time);
            end
            if (need_t_b !== need_t) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.need_t changed in tick B: %h -> %h at %0t",
                             need_t_b, need_t, $time);
            end
            if (qport_l_b !== qport_l) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.qport_l changed in tick B: %h -> %h at %0t",
                             qport_l_b, qport_l, $time);
            end
            if (rem_l_b !== rem_l) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.rem_l changed in tick B: %h -> %h at %0t",
                             rem_l_b, rem_l, $time);
            end
            if (l_pop_b !== l_pop) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.l_pop changed in tick B: %h -> %h at %0t",
                             l_pop_b, l_pop, $time);
            end
            if (lat_l_b !== lat_l) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.lat_l changed in tick B: %h -> %h at %0t",
                             lat_l_b, lat_l, $time);
            end
            if (ev_l_b !== ev_l) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.ev_l changed in tick B: %h -> %h at %0t",
                             ev_l_b, ev_l, $time);
            end
            if (cnt_l_b !== cnt_l) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.cnt_l changed in tick B: %h -> %h at %0t",
                             cnt_l_b, cnt_l, $time);
            end
            if (inflight_x_w_b !== inflight_x_w) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.inflight_x_w changed in tick B: %h -> %h at %0t",
                             inflight_x_w_b, inflight_x_w, $time);
            end
            if (t_disp_b !== t_disp) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.t_disp changed in tick B: %h -> %h at %0t",
                             t_disp_b, t_disp, $time);
            end
            if (t_mate_b !== t_mate) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.t_mate changed in tick B: %h -> %h at %0t",
                             t_mate_b, t_mate, $time);
            end
            if (ea_act_x_b !== ea_act_x) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.ea_act_x changed in tick B: %h -> %h at %0t",
                             ea_act_x_b, ea_act_x, $time);
            end
            if (sw_b !== sw) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.sw changed in tick B: %h -> %h at %0t",
                             sw_b, sw, $time);
            end
            if (flag_g_b !== flag_g) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.flag_g changed in tick B: %h -> %h at %0t",
                             flag_g_b, flag_g, $time);
            end
            if (t_flush_b !== t_flush) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.t_flush changed in tick B: %h -> %h at %0t",
                             t_flush_b, t_flush, $time);
            end
            if (g_io_b !== g_io) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.g_io changed in tick B: %h -> %h at %0t",
                             g_io_b, g_io, $time);
            end
            if (p_run_b !== p_run) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.p_run changed in tick B: %h -> %h at %0t",
                             p_run_b, p_run, $time);
            end
            if (t_take_b !== t_take) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.t_take changed in tick B: %h -> %h at %0t",
                             t_take_b, t_take, $time);
            end
            if (retry_t1_b !== retry_t1) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.retry_t1 changed in tick B: %h -> %h at %0t",
                             retry_t1_b, retry_t1, $time);
            end
            if (rq_g_b !== rq_g) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.rq_g changed in tick B: %h -> %h at %0t",
                             rq_g_b, rq_g, $time);
            end
            if (g_fetch_b !== g_fetch) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.g_fetch changed in tick B: %h -> %h at %0t",
                             g_fetch_b, g_fetch, $time);
            end
            if (g_abort_b !== g_abort) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.g_abort changed in tick B: %h -> %h at %0t",
                             g_abort_b, g_abort, $time);
            end
            if (nop_cand_b !== nop_cand) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.nop_cand changed in tick B: %h -> %h at %0t",
                             nop_cand_b, nop_cand, $time);
            end
            if (ir_now_l_b !== ir_now_l) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.ir_now_l changed in tick B: %h -> %h at %0t",
                             ir_now_l_b, ir_now_l, $time);
            end
            if (t_start_b !== t_start) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.t_start changed in tick B: %h -> %h at %0t",
                             t_start_b, t_start, $time);
            end
            if (t_flush_addr_b !== t_flush_addr) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.t_flush_addr changed in tick B: %h -> %h at %0t",
                             t_flush_addr_b, t_flush_addr, $time);
            end
            if (ps_base_b !== ps_base) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.ps_base changed in tick B: %h -> %h at %0t",
                             ps_base_b, ps_base, $time);
            end
            if (t_pops_b !== t_pops) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.t_pops changed in tick B: %h -> %h at %0t",
                             t_pops_b, t_pops, $time);
            end
            if (th_lift_t_b !== th_lift_t) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.th_lift_t changed in tick B: %h -> %h at %0t",
                             th_lift_t_b, th_lift_t, $time);
            end
            if (th_arm_t_b !== th_arm_t) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.th_arm_t changed in tick B: %h -> %h at %0t",
                             th_arm_t_b, th_arm_t, $time);
            end
            if (th_on_t_b !== th_on_t) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.th_on_t changed in tick B: %h -> %h at %0t",
                             th_on_t_b, th_on_t, $time);
            end
            if (th_arm_c_b !== th_arm_c) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.th_arm_c changed in tick B: %h -> %h at %0t",
                             th_arm_c_b, th_arm_c, $time);
            end
            if (th_pre_t_b !== th_pre_t) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.th_pre_t changed in tick B: %h -> %h at %0t",
                             th_pre_t_b, th_pre_t, $time);
            end
            if (th_held_b !== th_held) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.th_held changed in tick B: %h -> %h at %0t",
                             th_held_b, th_held, $time);
            end
            if (xfer_x_b !== xfer_x) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.xfer_x changed in tick B: %h -> %h at %0t",
                             xfer_x_b, xfer_x, $time);
            end
            if (g_slot_fetch_b !== g_slot_fetch) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.g_slot_fetch changed in tick B: %h -> %h at %0t",
                             g_slot_fetch_b, g_slot_fetch, $time);
            end
            if (abort_loop_b !== abort_loop) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.abort_loop changed in tick B: %h -> %h at %0t",
                             abort_loop_b, abort_loop, $time);
            end
            if (rs_fire_b !== rs_fire) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.rs_fire changed in tick B: %h -> %h at %0t",
                             rs_fire_b, rs_fire, $time);
            end
            if (rt_set_b !== rt_set) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.rt_set changed in tick B: %h -> %h at %0t",
                             rt_set_b, rt_set, $time);
            end
            if (rt_now_b !== rt_now) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.rt_now changed in tick B: %h -> %h at %0t",
                             rt_now_b, rt_now, $time);
            end
            if (rt_n_b !== rt_n) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.rt_n changed in tick B: %h -> %h at %0t",
                             rt_n_b, rt_n, $time);
            end
            if (rt_fire_b !== rt_fire) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.rt_fire changed in tick B: %h -> %h at %0t",
                             rt_fire_b, rt_fire, $time);
            end
            if (flag_x_b !== flag_x) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.flag_x changed in tick B: %h -> %h at %0t",
                             flag_x_b, flag_x, $time);
            end
            if (inflight_c_b !== inflight_c) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.inflight_c changed in tick B: %h -> %h at %0t",
                             inflight_c_b, inflight_c, $time);
            end
            if (t_sth_b !== t_sth) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.t_sth changed in tick B: %h -> %h at %0t",
                             t_sth_b, t_sth, $time);
            end
            if (t_sth_inf_b !== t_sth_inf) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.t_sth_inf changed in tick B: %h -> %h at %0t",
                             t_sth_inf_b, t_sth_inf, $time);
            end
            if (t_sth_n_b !== t_sth_n) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.t_sth_n changed in tick B: %h -> %h at %0t",
                             t_sth_n_b, t_sth_n, $time);
            end
            if (sh_held_t_b !== sh_held_t) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.sh_held_t changed in tick B: %h -> %h at %0t",
                             sh_held_t_b, sh_held_t, $time);
            end
            if (sh_set_b !== sh_set) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.sh_set changed in tick B: %h -> %h at %0t",
                             sh_set_b, sh_set, $time);
            end
            if (sh_fire_b !== sh_fire) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.sh_fire changed in tick B: %h -> %h at %0t",
                             sh_fire_b, sh_fire, $time);
            end
            if (sh_n_b !== sh_n) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.sh_n changed in tick B: %h -> %h at %0t",
                             sh_n_b, sh_n, $time);
            end
            if (room_t_b !== room_t) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.room_t changed in tick B: %h -> %h at %0t",
                             room_t_b, room_t, $time);
            end
            if (want_tk_b !== want_tk) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: queue.want_tk changed in tick B: %h -> %h at %0t",
                             want_tk_b, want_tk, $time);
            end
        end
    end
    final if (chk_on && chk_n != 0)
        $display("v35 chk: queue: %0d changes in tick B", chk_n);
    /* verilator lint_on BLKSEQ */
`endif
    // (S7b) chk end

    wire unused = &{1'b0, ce_b, dlv_addr[19:1]};
endmodule
