`timescale 1ns/1ps

// V35S core v2: the bus unit (docs/v35s-core-v2.md, "Modules and the state they own"; Appendix
// B §1 "Bus unit (BIU)"). One cycle at a time: B1, B2, waits, B3. A cycle granted on CPU clock
// s with w waits occupies s .. s+2+w (bus.py); its last clock is B3 and its datum is delivered
// on the next clock (data_ready=0), from the delivery registers written at the edge that ends
// the cycle. Memory cycles and fetches take WTC field 0's waits, I/O cycles and the on-chip
// SFR store field 7's (sfr_cycle=io: 3 + the I/O waits, never on the pins).
//
// The pin timing and the read latch are v35_biu.sv's (lines 290-350), verbatim: a cycle granted
// on clock s shows B1 on the pins in the CPU state after s's `ce`; /MREQ (or /REFRQ) falls
// mid-B1, /IOSTB and a read's /MSTB mid-B2, a memory write's /MSTB mid-way through the state
// before B3, every strobe rises mid-B3, where read data is latched.
//
// Clocking: `ce` ends a CPU clock; the registers hold the state at the end of the last clock.
// Everything this module outputs is stage S0 (registers only) except the grant inputs, which
// are S4 and are written at the edge.
//
// Registered state (widths) and the model variables it replaces:
//   c_valid 1, c_kind 3, c_pos 3, c_len 3, c_addr 20, c_width 2, c_data 16, c_dsel 2 (S4: the
//   datum at B2), c_internal 1,
//   c_ext 1                                  bus.current (kind, t - start, length, ...)
//   c_b2b 1, c_commit 1, c_on_start 1, c_run 1  Cycle.b2b / .commit; cur.start == start_clock
//                                            (eu.py io_exec); _fetch_run (arbiter.py:458)
//   c_after_post 1, c_disp_in_flight 1, c_ir_before 1   (S4) Cycle flags set at a fetch's
//                                            start: a memory request waited in the slot (x.start >
//                                            pfree, eu.py:1794), a displacement taken while it was
//                                            in flight (queue._disp_in_flight), the IR held an
//                                            opcode (queue._page_b2b's ir_t <= bus_start); read by
//                                            S5's page rules
//   (S5b) c_thru 1                           Cycle.thru (page_cl=thru: issued in a 0F read's cl
//                                            clocks)
//   (S5b) c_pfa 1                            the fetch issued while a 0F read (pfree) waited in
//                                            the slot: x.start > pfree (page_commit=post)
//   (S5b) c_tn 1, c_tkin 1, tk_prev 1        _page_b2b's window: the form's last take at or after
//                                            the clock before the fetch's issue (take_t >=
//                                            bus_start - 1), or page_b2b_win=run's look-back
//                                            (the fetch before it, back to back, took it after
//                                            its issue clock: carried at the issue); a take in
//                                            this fetch after its issue clock; a take on t-1
//   (S5b) c_as 1, c_nt 1                     _page_imm_run: the fetch issued after the running
//                                            form's start clock (prev.start > start_clock), no
//                                            take on or after its issue clock (> take_t)
//   (c_ir_before (S4) is kept up: cleared when a start empties the IR after the issue)
//   (c_lea_start: not built: lea_wb=fetch is the sequencer's lw_*)
//   dlv_v 1, dlv_kind 3, dlv_addr 20, dlv_width 2, done_data 16
//                                            the cycle that ended on t-1 (bus.completed), its
//                                            read datum (latched mid-B3)
//   gap 1                                    last_end + min_gap (+ the disp_io clock)
//   f_since 4                                t - last_fetch_end (0 while a fetch runs, sat 15)
//   io_tail 2                                t <= last_io_end + io_recover
//   wl 3                                     wlatch_until - t (the data latch, wlatch 4)
//   ab_v 1, ab_pos 2                         queue.abort_end (the 3-clock aborted fetch cycle:
//                                            nothing on the pins, the bus stays free)
//   (S5a) w_v 1, w_ncyc 2, w_rel 5           the last memory write among bus.cycles[-3:]
//                                            (str_single_start=write): set, the cycles started
//                                            after it (sat 3), its last clock - t (signed, sat)
module v35_bus
    import v35_front_pkg::*;
(
    input  wire        clock,
    input  wire        reset_n,
    input  wire        ce,          // end of a CPU clock
    input  wire        ce_mid,      // the middle of a CPU clock (strobe edges)
    input  wire [15:0] wtc,
    input  wire [7:0]  rfm,         // RFM.RFW: a refresh cycle's length

    // S4: the grant (the arbiter's choice for this clock)
    input  wire        g_start,
    input  wire [2:0]  g_kind,
    input  wire [19:0] g_addr,
    input  wire [1:0]  g_width,
    input  wire [15:0] g_data,
    input  wire        g_ext,       // disp_io=extend (S4: zero in S2)
    input  wire        g_b2b,       // a fetch the bus unit committed to back to back (b2b_at)
    input  wire        g_thru,      // page_cl=thru (S5: zero in S2)
    // the other cycle flags set at start (S4/S5; named zero inputs in S2): after_post,
    // lea_start, disp_in_flight, ir_before, take_near
    input  wire        g_after_post,
    input  wire        g_lea_start,
    input  wire        g_disp_in_flight,
    input  wire        g_ir_before,
    input  wire        g_take_near,
    input  wire        g_abort,     // the aborted fetch cycle starts (abort_fetch=retry)
    input  wire        g_slot,      // the left-out write's slot (slot_latch: the data latch)
    input  wire        g_wl_io,     // (S5a) a string form's I/O write issued (str_io_latch=write)
    input  wire [1:0]  g_dsel,      // (S4) the write datum taken at B2 (store_imm's immediate)
    input  wire [15:0] wd_imm,      // ... the EU's immediate on that clock
    input  wire        disp_take,   // a displacement taken on this clock (c_disp_in_flight)
    input  wire        take_any,    // (S5b) an operand take on this clock (T or P: take_t == t)
    input  wire        flush_now,   // (S5b) a flush empties the IR on this clock
    // S5: the clock's instruction starts (an I/O issue clock's second pass included)
    input  wire        start_any,
    // the data latch's fills on this clock other than a write's issue (S2/S5: a register
    // form's last operand byte, wlatch_imm=reg_last; the left-out write's slot, S4)
    input  wire        wl_fill_t,
    input  wire        wl_fill_p,       // (the second pass's: the next state only)

    // S0
    output wire        busy,            // a cycle started on an earlier clock runs on t
    output wire        free,            // bus.free(t)
    output wire [2:0]  cur_kind,        // that cycle (K_NONE: idle)
    output wire [2:0]  cur_pos,         // t - start
    output wire [2:0]  cur_left,        // end + 1 - t: its clocks left, this one included
    output wire        cur_on_start,    // it started on the running instruction's start clock
    output wire        in_wait,         // bus.in_wait(t)
    output wire        fetch_inflight,  // bus.fetch_inflight(t)
    output wire        fetch_past_b2,   // a fetch past its second clock (start + 2 <= t)
    output wire        fetch_end_prev,  // last_fetch_end == t-1
    output wire        cpu_end_prev,    // a non-fetch cycle ended on t-1 (retry_after)
    output wire [3:0]  fetch_since,     // t - last_fetch_end (0 while one runs, sat 15)
    output wire        fetch_run_prev,  // _fetch_run(t): the fetch that ended on t-1 ran b2b
    output wire        io_win,          // t <= last_io_end + io_recover
    output wire        wl_busy,         // t < wlatch_until (this clock's delivery fill in)
    output wire        wl_busy_x,       // ... and this clock's other fills (S5 reads it)
    output wire        dlv_v,           // the cycle that ended on t-1 ...
    output wire [2:0]  dlv_kind,
    output wire [19:0] dlv_addr,
    output wire [1:0]  dlv_width,
    output reg  [15:0] done_data,       // ... its read datum (latched mid-B3)
    output wire        abort_busy,      // an aborted cycle is in flight (abort_end >= t)
    output wire        abort_last,      // abort_end == t
    output wire        abort_done,      // abort_end == t-1 (queue.abort_done in phase C)
    output wire [2:0]  fetch_len,       // bus.length("fetch")
    output wire [2:0]  grant_len,       // the length of the granted cycle
    output reg         error,           // a start on a bus that was not free (sticky)
    output wire        w3_v,            // (S5a) a memory write is among the last three cycles ...
    output wire signed [4:0] w3_rel,    //   ... its last clock - t
    // (S5b) the 0F page: the fetch on the bus (S0) ...
    output wire        cur_thru,        // ... c_thru (page_cl=thru)
    output wire        cur_b2b_pfa,     // ... committed back to back after a 0F read's post
    output wire        cf_tn,           // ... take_near (page_b2b=reg, page_b2b_win=run)
    output wire        cf_irb,          // ... the IR held an opcode loaded no later than its issue
    output wire        prev_imm,        // the fetch that ended on t-1 issued after the running
                                        //   form's start and no take since (page_imm_run)

    // pins (as v35s_model.sv)
    output reg         a0,
    output reg         a19,
    output reg         a18_ube,
    output reg  [8:0]  mux_address,
    output reg  [15:0] data_out,
    output reg         mreq_n,
    output reg         mstb_n,
    output reg         iostb_n,
    output reg         read_write,
    output reg         refrq_n,
    input  wire [15:0] data_in
);
    function automatic logic [2:0] rf_len(input logic [1:0] rfw);   // 3 + RFM.RFW
        case (rfw)
            2'd0: rf_len = 3'd3;
            2'd1: rf_len = 3'd4;
            default: rf_len = 3'd5;
        endcase
    endfunction

    // ------------------------------------------------ registered state (end of clock)
    reg         c_valid = 1'b0;
    reg  [2:0]  c_kind = K_NONE;
    reg  [2:0]  c_pos = 3'd0;
    reg  [2:0]  c_len = 3'd0;
    reg         c_ext = 1'b0;
    reg         c_internal = 1'b0;
    reg  [19:0] c_addr = 20'd0;
    reg  [1:0]  c_width = BW_WORD;
    reg  [15:0] c_data = 16'd0;
    reg  [1:0]  c_dsel = 2'd0;
    reg         c_b2b = 1'b0;
    reg         c_commit = 1'b0;
    reg         c_on_start = 1'b0;
    reg         c_run = 1'b0;
    reg         c_after_post = 1'b0;
    reg         c_disp_in_flight = 1'b0;
    reg         c_ir_before = 1'b0;
    reg         c_thru = 1'b0;      // (S5b)
    reg         c_pfa = 1'b0;
    reg         c_tn = 1'b0;
    reg         c_tkin = 1'b0;
    reg         tk_prev = 1'b0;
    reg         c_as = 1'b0;
    reg         c_nt = 1'b0;
    reg         gap = 1'b0;
    reg  [3:0]  f_since = 4'd9;     // last_fetch_end = -10: at the end of clock -1, 9
    reg  [1:0]  io_tail = 2'd0;
    reg  [2:0]  wl = 3'd0;
    reg         ab_v = 1'b0;
    reg  [1:0]  ab_pos = 2'd0;
    reg         d_v = 1'b0;
    reg  [2:0]  d_kind = K_NONE;
    reg  [19:0] d_addr = 20'd0;
    reg  [1:0]  d_width = BW_WORD;
    reg         w_v = 1'b0;
    reg  [1:0]  w_ncyc = 2'd0;
    reg  signed [4:0] w_rel = 5'sd0;
    assign w3_v = w_v && w_ncyc <= 2'd2;
    assign w3_rel = w_rel;

    // ------------------------------------------------ S0
    wire last_clock = c_valid && c_pos == c_len - 3'd1;
    assign busy = c_valid && !last_clock;
    wire [2:0] pos_now = c_pos + 3'd1;
    assign cur_kind = busy ? c_kind : K_NONE;
    assign cur_pos = busy ? pos_now : 3'd0;
    assign cur_left = busy ? c_len - pos_now : 3'd0;
    assign cur_on_start = busy && c_on_start;
    assign in_wait = busy && !k_io(c_kind) && pos_now >= 3'd2 && pos_now < c_len - 3'd1;
    assign fetch_inflight = busy && c_kind == K_FETCH;
    assign fetch_past_b2 = fetch_inflight && pos_now >= 3'd2;
    assign free = !busy && !gap;
    assign fetch_since = fetch_inflight ? 4'd0 : (f_since == 4'd15 ? 4'd15 : f_since + 4'd1);
    assign fetch_end_prev = fetch_since == 4'd1;
    assign fetch_run_prev = fetch_end_prev && c_kind == K_FETCH && c_run;
    assign cpu_end_prev = d_v && d_kind != K_FETCH;
    assign io_win = (busy && k_io(c_kind)) || io_tail != 2'd0;
    assign dlv_v = d_v;
    assign dlv_kind = d_kind;
    assign dlv_addr = d_addr;
    assign dlv_width = d_width;
    assign abort_busy = ab_v && ab_pos != 2'd2;
    assign abort_last = ab_v && ab_pos == 2'd1;
    assign abort_done = ab_v && ab_pos == 2'd2;
    // (S5b) the 0F page's flags of the fetch on the bus / the one that ended on t-1
    assign cur_thru = fetch_inflight && c_thru;
    assign cur_b2b_pfa = fetch_inflight && c_b2b && c_pfa;
    assign cf_tn = c_tn;
    assign cf_irb = c_ir_before;
    assign prev_imm = fetch_end_prev && c_kind == K_FETCH && c_as && c_nt;
    // page_b2b_win=run: a fetch issued back to back after one that took the form's last take
    // after its issue clock takes the window over
    wire tn_carry = fetch_end_prev && c_kind == K_FETCH && c_tkin;

    // the data latch: a read's datum on its delivery clock (eu.complete), a write from its
    // issue (eu.issue), a register form's last operand byte (wl_fill)
    wire [2:0] wl_now = wl == 3'd0 ? 3'd0 : wl - 3'd1;
    wire fill_c = d_v && (d_kind == K_READ || d_kind == K_IO_READ);
    wire fill_x = (g_start && (g_kind == K_WRITE || (g_kind == K_IO_WRITE && g_wl_io)))
                  || wl_fill_t || g_slot;
    wire [2:0] wl_fill_v = wl_now > 3'(FIT_WLATCH) ? wl_now : 3'(FIT_WLATCH);
    wire [2:0] wl_c = fill_c ? wl_fill_v : wl_now;
    wire [2:0] wl_x = (fill_c || fill_x) ? wl_fill_v : wl_now;
    wire [2:0] wl_e = (fill_c || fill_x || wl_fill_p) ? wl_fill_v : wl_now;
    assign wl_busy = wl_c != 3'd0;
    assign wl_busy_x = wl_x != 3'd0;

    // lengths: bus.length(kind), the SFR store's I/O waits
    wire [1:0] waits_mem = wtc[WTC_MEM_LSB +: 2];
    wire [1:0] waits_io = wtc[WTC_IO_LSB +: 2];
    wire g_sfr = g_kind == K_WRITE && g_addr >= SFR_PAGE;
    assign grant_len = g_kind == K_REFRESH ? rf_len(rfm[3:2]) :
                       (k_io(g_kind) || g_sfr) ? 3'(BUS_BASE) + 3'(waits_io) :
                       3'(BUS_BASE) + 3'(waits_mem);
    assign fetch_len = 3'(BUS_BASE) + 3'(waits_mem);

    // ------------------------------------------------ the end of the clock (S6)
    wire fetch_x = g_start && g_kind == K_FETCH;
    always @(posedge clock) begin
        if (!reset_n) begin
            c_valid <= 1'b0;
            c_kind <= K_NONE;
            c_pos <= 3'd0;
            c_len <= 3'd0;
            c_ext <= 1'b0;
            c_internal <= 1'b0;
            c_b2b <= 1'b0;
            c_commit <= 1'b0;
            c_on_start <= 1'b0;
            c_run <= 1'b0;
            gap <= 1'b0;
            f_since <= 4'd9;
            io_tail <= 2'd0;
            wl <= 3'd0;
            ab_v <= 1'b0;
            ab_pos <= 2'd0;
            d_v <= 1'b0;
            error <= 1'b0;
        end else if (ce) begin
            wl <= wl_e;
            f_since <= fetch_x ? 4'd0 : fetch_since;
            // (S5a) the last memory write (its last clock relative to the next clock)
            if (g_start && g_kind == K_WRITE) begin
                w_v <= 1'b1;
                w_ncyc <= 2'd0;
                w_rel <= 5'(grant_len) - 5'sd2;
            end else begin
                if (g_start && w_ncyc != 2'd3)
                    w_ncyc <= w_ncyc + 2'd1;
                if (w_rel != -5'sd16)
                    w_rel <= w_rel - 5'sd1;
            end
            // the delivery registers: the cycle whose last clock is this one
            d_v <= busy && pos_now == c_len - 3'd1;
            d_kind <= c_kind;
            d_addr <= c_addr;
            d_width <= c_width;
            if (g_start) begin
                if (!free)
                    error <= 1'b1;
                c_valid <= 1'b1;
                c_kind <= g_kind;
                c_pos <= 3'd0;
                c_len <= grant_len;
                c_ext <= g_ext;
                c_internal <= g_sfr;
                c_addr <= g_addr;
                c_width <= g_width;
                c_data <= g_data;
                c_dsel <= g_dsel;
                c_b2b <= g_b2b;
                c_commit <= g_b2b;
                c_on_start <= start_any;
                c_run <= fetch_x && fetch_end_prev;
                c_after_post <= fetch_x && g_after_post;
                c_ir_before <= fetch_x && g_ir_before;
                c_disp_in_flight <= 1'b0;
                c_thru <= fetch_x && g_thru;
                c_pfa <= fetch_x && g_after_post;
                c_tn <= tk_prev || take_any || tn_carry;
                c_tkin <= 1'b0;
                c_as <= !start_any;
                c_nt <= !take_any;
                gap <= g_ext || FIT_MIN_GAP != 0;
            end else begin
                if (busy)
                    c_pos <= pos_now;
                else
                    c_valid <= 1'b0;
                if (!busy)
                    gap <= 1'b0;
                if (start_any)
                    c_on_start <= 1'b0;     // another instruction started: not its start clock
                if (busy && c_kind == K_FETCH && disp_take)
                    c_disp_in_flight <= 1'b1;
                // (S5b) the window flags through the cycle's flight
                if (busy && take_any) begin
                    c_tn <= 1'b1;
                    c_tkin <= 1'b1;
                    c_nt <= 1'b0;
                end
                if (busy && start_any)
                    c_as <= 1'b0;
                if (start_any || flush_now)
                    c_ir_before <= 1'b0;
            end
            tk_prev <= take_any;
            if (g_start && k_io(g_kind))
                io_tail <= 2'(FIT_IO_RECOVER);
            else if (!(busy && k_io(c_kind)) && !(gap && c_ext) && io_tail != 2'd0)
                io_tail <= io_tail - 2'd1;      // (disp_io=extend: from the clock after its last)
            if (g_abort) begin
                ab_v <= 1'b1;
                ab_pos <= 2'd0;
            end else if (ab_v) begin
                if (ab_pos == 2'd2)
                    ab_v <= 1'b0;
                else
                    ab_pos <= ab_pos + 2'd1;
            end
        end
    end

    // ------------------------------------------------ pins (v35_biu.sv:290-350)
    wire        n_valid = g_start || busy;
    wire [2:0]  n_kind = g_start ? g_kind : c_kind;
    wire [2:0]  n_pos = g_start ? 3'd0 : pos_now;
    wire [19:0] n_addr = g_start ? g_addr : c_addr;
    wire [1:0]  n_width = g_start ? g_width : c_width;
    wire [15:0] n_data = g_start ? g_data : c_data;
    wire        n_internal = g_start ? g_sfr : c_internal;
    wire        n_write = n_kind == K_WRITE || n_kind == K_IO_WRITE;
    wire        c_write = c_kind == K_WRITE || c_kind == K_IO_WRITE;
    wire        pins = c_valid && !c_internal;
    reg  [8:0]  refresh_row = 9'd0;

    initial begin
        a0 = 1'b0;
        a19 = 1'b0;
        a18_ube = 1'b0;
        mux_address = 9'd0;
        data_out = 16'd0;
        mreq_n = 1'b1;
        mstb_n = 1'b1;
        iostb_n = 1'b1;
        read_write = 1'b1;
        refrq_n = 1'b1;
        done_data = 16'hffff;
    end

    always @(posedge clock) begin
        if (!reset_n) begin
            mreq_n <= 1'b1;
            mstb_n <= 1'b1;
            iostb_n <= 1'b1;
            refrq_n <= 1'b1;
            read_write <= 1'b1;
            refresh_row <= 9'd0;
        end else if (ce) begin
            if (!n_valid || n_internal) begin
                read_write <= 1'b1;
            end else if (n_pos == 3'd0) begin
                // B1: the row (A17..A9), A19, A18 and A0
                read_write <= !n_write;
                if (n_kind == K_REFRESH) begin
                    mux_address <= refresh_row;
                    refresh_row <= refresh_row + 1'b1;
                    a0 <= 1'b0;
                    a19 <= 1'b0;
                    a18_ube <= 1'b0;
                end else begin
                    mux_address <= n_addr[17:9];
                    a0 <= n_addr[0];
                    a19 <= n_addr[19];
                    a18_ube <= n_addr[18];
                end
            end else if (n_pos == 3'd1 && n_kind != K_REFRESH) begin
                // B2: the column (A9, A8..A1), /UBE, the write data
                mux_address <= {n_addr[9], n_addr[8:1]};
                a18_ube <= n_width == BW_LO;
                if (n_write)
                    data_out <= (g_start || c_dsel == 2'd0) ? n_data
                              : c_dsel == 2'd1 ? wd_imm
                              : c_dsel == 2'd2 ? {wd_imm[7:0], 8'd0} : {8'd0, wd_imm[15:8]};
            end
        end else if (ce_mid && pins) begin
            if (c_pos == 3'd0) begin
                if (c_kind == K_REFRESH)
                    refrq_n <= 1'b0;
                else
                    mreq_n <= 1'b0;
            end else if (c_pos == c_len - 3'd1) begin
                mreq_n <= 1'b1;
                mstb_n <= 1'b1;
                iostb_n <= 1'b1;
                refrq_n <= 1'b1;
            end else if (c_kind != K_REFRESH) begin
                if (k_io(c_kind))
                    iostb_n <= 1'b0;
                else if (!c_write || c_pos == c_len - 3'd2)
                    mstb_n <= 1'b0;
            end
        end
    end

    // read data: latched mid-B3, delivered on the next CPU clock
    always @(posedge clock) begin
        if (ce_mid && c_valid && c_pos == c_len - 3'd1 && k_read(c_kind) && !c_internal)
            done_data <= data_in;
    end

    wire unused = &{1'b0, c_commit, g_lea_start, g_disp_in_flight,
                    g_take_near, c_after_post, c_disp_in_flight, wtc[13:2],
                    rfm[7:4], rfm[1:0]};
endmodule
