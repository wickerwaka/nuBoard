`timescale 1ns/1ps
`include "v35_macros.svh"

// V35S core v2: the bus unit (docs/v35s-core-v2.md, "Modules and the state they own"; Appendix
// B §1 "Bus unit (BIU)"; (A1) docs/v35s-arbiter-strategy.md §2). One cycle at a time: B1, B2,
// waits, B3. A cycle granted on CPU clock s with w waits occupies s .. s+2+w (bus.py); its last
// clock is B3 and its datum is delivered on the next clock (data_ready=0), from the delivery
// registers written at the edge that ends the cycle. Memory cycles and fetches take WTC field
// 0's waits, I/O cycles and the on-chip SFR store field 7's (sfr_cycle=io: 3 + the I/O waits,
// never on the pins).
//
// The pin timing and the read latch are v35_biu.sv's (lines 290-350), verbatim: a cycle granted
// on clock s shows B1 on the pins in the CPU state after s's `ce_a`; /MREQ (or /REFRQ) falls
// mid-B1, /IOSTB and a read's /MSTB mid-B2, a memory write's /MSTB mid-way through the state
// before B3, every strobe rises mid-B3, where read data is latched.
//
// (A1) The grant. The arbiter is gone: the bus unit grants its own cycles from two request
// ports, the EU's and the queue's, by one fixed priority evaluated once a clock on a free bus:
//   0. the odd word's second half (the bus unit's own pair: a memory word at an odd address
//      runs hi, then lo), and the aborted fetch (a back-to-back commitment whose line fell with
//      no EU request standing; (Q2) the triple clock: the start, an operand take and the IR
//      load on one clock with the line at exactly a word's room);
//   1. the fetch committed back to back (the line up at the last clock of the fetch that just
//      ended, no EU request or reservation standing then: `b2b`, held by req_v || req_resv);
//   2. the EU's request (`req_v`; a memory cycle not within io_recover clocks of an I/O cycle);
//   3. the queue's fetch, when its line is up and the EU's reservation is down, or the queue is
//      low and the reservation is a memory cycle's: an I/O cycle's reservation is absolute
//      (`fetch_req && (!req_resv || (q_low && req_cyc is memory))`);
//   4. nothing.
// The EU request port is the cycle type (memory read / write, I/O read / write), the address,
// the width (byte / word), the datum (taken at B2) and the reservation; the bus unit answers
// `req_ack` (the request's first cycle issued now) and `req_done` (its last cycle ended on the
// last clock, the datum in `done_data`). Nothing on the port names an instruction: the bus
// unit knows no form, class, row, step or count. The grant is a handful of terms on registered
// facts (the cycle's position, b2b, the pair's half) and the two request lines: four levels.
//
// Clocking: `ce_a` ends a CPU clock; the registers hold the state at the end of the last clock.
// Everything this module outputs is stage S0 (registers only) except the grant, which is S4 and
// is written at the edge.
//
// Registered state (widths) and the model variables it replaces:
//   c_valid 1, c_kind 3, c_pos 3, c_len 3, c_addr 20, c_width 2, c_half 2, c_internal 1
//                                            bus.current (kind, t - start, length, ...)
//   c_run 1                                  _fetch_run (arbiter.py:458)
//   p2_v 1                                   (A1) the odd word's second half is next
//   dlv_v 1, dlv_kind 3, dlv_addr 20, dlv_width 2, d_p1 1, done_data 16
//                                            the cycle that ended on t-1 (bus.completed), its
//                                            read datum (latched mid-B3); d_p1: the pair's first
//   f_since 4                                t - last_fetch_end (0 while a fetch runs, sat 15)
//   io_tail 2                                t <= last_io_end + io_recover
//   ab_v 1, ab_pos 2                         queue.abort_end (the 3-clock aborted fetch cycle:
//                                            nothing on the pins, the bus stays free)
//   (S5a) w_v 1, w_ncyc 2, w_rel 5           the last memory write among bus.cycles[-3:]
//                                            (str_single_start=write): set, the cycles started
//                                            after it (sat 3), its last clock - t (signed, sat)
//   (Q1) b2b 1                               the request line sampled high at a fetch's last
//                                            clock, no EU request standing: the next fetch back
//                                            to back (b2b_at)
module v35_bus
    import v35_front_pkg::*;
(
    input  wire        clock,
    input  wire        reset_n,
    input  wire        ce_a,          // end of a CPU clock
    input  wire        ce_b,          // (S7b) the CPU clock's second tick (the pipeline registers)
    input  wire        ce_e,        // (S7b) the CPU clock's edge (the pins' B1 / B2)
    input  wire        ce_mid,      // the middle of a CPU clock (strobe edges)
    input  wire [15:0] wtc,
    input  wire [7:0]  rfm,         // RFM.RFW: a refresh cycle's length

    // (A1) the EU's request port (tick A)
    input  wire        req_v,       // a cycle is wanted (a level: stands until acknowledged)
    input  wire [1:0]  req_cyc,     // RQ_MEMR, RQ_MEMW, RQ_IOR, RQ_IOW
    input  wire [19:0] req_addr,    // the cycle's address (the pair's second half's after req_ack)
    input  wire        req_width,   // 1: a word (at an odd memory address: the bus unit's pair)
    input  wire [15:0] req_data,    // a write's datum, taken at B2 (lane-placed for a byte)
    input  wire        req_resv,    // the reservation: no fetch starts while it is up (unless q_low)
    output wire        req_ack,     // the request's first cycle issued now (S4)
    output wire        req_done,    // its last cycle ended on t-1 (S0; the datum in done_data)
    // the queue (Q1): the request line, the priority hint, the address
    input  wire        fetch_req,
    input  wire        q_low,
    input  wire        q_word,      // (Q2) the line up with room for exactly a word
    input  wire [19:0] fetch_addr,
    // (Q2) the aborted fetch's queue events only: three reads on one clock (the start's opcode,
    // an operand take, the IR load)
    input  wire        t_start,
    input  wire        take_now,
    input  wire        l_pop,

    // S4: the grant, as the queue, the EU and the trace read it
    output wire        g_start,         // a cycle starts now (a fetch or an EU cycle)
    output wire [2:0]  g_kind,
    output wire [19:0] g_addr,
    output wire [1:0]  g_width,
    output wire        g_fetch,         // a fetch issued now
    output wire        g_eu,            // an EU cycle issued now (either half of a pair)
    output wire        g_abort,         // the aborted fetch cycle starts now
    output wire        g_b2b,           // the fetch issued now was committed back to back
    output wire        b2b_now,         // (Q1) the line was high at the last clock, a fetch's last

    // S0
    output wire        busy,            // a cycle started on an earlier clock runs on t
    output wire        free,            // bus.free(t)
    output wire [2:0]  cur_kind,        // that cycle (K_NONE: idle)
    output wire [2:0]  cur_pos,         // t - start
    output wire [2:0]  cur_left,        // end + 1 - t: its clocks left, this one included
    output wire        in_wait,         // bus.in_wait(t)
    output wire        fetch_inflight,  // bus.fetch_inflight(t)
    output wire        fetch_past_b2,   // a fetch past its second clock (start + 2 <= t)
    output wire        fetch_end_prev,  // last_fetch_end == t-1
    output wire        cpu_end_prev,    // a non-fetch cycle ended on t-1 (retry_after)
    output wire [3:0]  fetch_since,     // t - last_fetch_end (0 while one runs, sat 15)
    output wire        fetch_run_prev,  // _fetch_run(t): the fetch that ended on t-1 ran b2b
    output wire        io_win,          // t <= last_io_end + io_recover
    output wire        dlv_v,           // the cycle that ended on t-1 ...
    output wire [2:0]  dlv_kind,
    output wire [19:0] dlv_addr,
    output wire [1:0]  dlv_width,
    output wire [15:0] done_data,       // ... its read datum (on the pins mid-B3: (S7b) live
                                        //   through the delivery clock, then latched)
    output wire        abort_busy,      // an aborted cycle is in flight (abort_end >= t)
    output wire        abort_last,      // abort_end == t
    output wire        abort_done,      // abort_end == t-1 (queue.abort_done in phase C)
    output wire [2:0]  fetch_len,       // bus.length("fetch")
    output wire [2:0]  grant_len,       // the length of the granted cycle
    output reg         error,           // a start on a bus that was not free (sticky)
    output wire        w3_v,            // (S5a) a memory write is among the last three cycles ...
    output wire signed [4:0] w3_rel,    //   ... its last clock - t

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
    reg         c_internal = 1'b0;
    reg  [19:0] c_addr = 20'd0;
    reg  [1:0]  c_width = BW_WORD;
    reg  [1:0]  c_half = 2'd0;      // (A1) 0: a cycle of its own, 1: a pair's first, 2: its second
    reg         c_run = 1'b0;
    reg         p2_v = 1'b0;        // (A1) the pair's second half is next
    reg  [3:0]  f_since = 4'd9;     // last_fetch_end = -10: at the end of clock -1, 9
    reg  [1:0]  io_tail = 2'd0;
    reg         ab_v = 1'b0;
    reg  [1:0]  ab_pos = 2'd0;
    reg         d_v = 1'b0;
    reg  [2:0]  d_kind = K_NONE;
    reg  [19:0] d_addr = 20'd0;
    reg  [1:0]  d_width = BW_WORD;
    reg         d_p1 = 1'b0;
    reg         w_v = 1'b0;
    reg  [1:0]  w_ncyc = 2'd0;
    reg  signed [4:0] w_rel = 5'sd0;
    reg         b2b = 1'b0;
    assign b2b_now = b2b;
    assign w3_v = w_v && w_ncyc <= 2'd2;
    assign w3_rel = w_rel;

    // ------------------------------------------------ S0
    wire last_clock = c_valid && c_pos == c_len - 3'd1;
    assign busy = c_valid && !last_clock;
    wire [2:0] pos_now = c_pos + 3'd1;
    assign cur_kind = busy ? c_kind : K_NONE;
    assign cur_pos = busy ? pos_now : 3'd0;
    assign cur_left = busy ? c_len - pos_now : 3'd0;
    assign in_wait = busy && !k_io(c_kind) && pos_now >= 3'd2 && pos_now < c_len - 3'd1;
    assign fetch_inflight = busy && c_kind == K_FETCH;
    assign fetch_past_b2 = fetch_inflight && pos_now >= 3'd2;
    assign free = !busy;            // (min_gap 0; (A1) disp_io=extend's gap clock not built)
    assign fetch_since = fetch_inflight ? 4'd0 : (f_since == 4'd15 ? 4'd15 : f_since + 4'd1);
    assign fetch_end_prev = fetch_since == 4'd1;
    assign fetch_run_prev = fetch_end_prev && c_kind == K_FETCH && c_run;
    assign cpu_end_prev = d_v && d_kind != K_FETCH;
    assign req_done = cpu_end_prev && !d_p1;
    assign io_win = (busy && k_io(c_kind)) || io_tail != 2'd0;
    assign dlv_v = d_v;
    assign dlv_kind = d_kind;
    assign dlv_addr = d_addr;
    assign dlv_width = d_width;
    assign abort_busy = ab_v && ab_pos != 2'd2;
    assign abort_last = ab_v && ab_pos == 2'd1;
    assign abort_done = ab_v && ab_pos == 2'd2;

    // ------------------------------------------------ S4: the grant (one priority)
    wire [2:0]  rq_kind = req_cyc == RQ_MEMR ? K_READ : req_cyc == RQ_MEMW ? K_WRITE
                        : req_cyc == RQ_IOR ? K_IO_READ : K_IO_WRITE;
    wire        rq_mem = !req_cyc[1];
    wire        rq_two = req_width && req_addr[0] && rq_mem;   // the pair: hi, then lo
    // io_recover as the bus unit's turnaround (A1_IOREC 1: no EU memory cycle within io_recover
    // clocks of an I/O cycle; 2: no EU cycle at all; 0: the EU's own wait, not here)
    wire        rq_turn = (`A1_IOREC == 1 && rq_mem) || `A1_IOREC == 2;
    wire        eu_ok = req_v && !(rq_turn && io_win);
    // rule 3: the queue's low hint overrides a memory cycle's reservation only (A1_IOQL 0: any
    // reservation, the strategy's first wording, kept for the record)
    wire        fq_ok = fetch_req && (!req_resv || (q_low && !(`A1_IOQL && !rq_mem)))
                        && !ioh_hold;
    wire        tri3 = t_start && take_now && l_pop;
    // (MX1g) V35_MX1G_IOH: the request line that rises on the clock this unit issues an EU I/O
    // cycle, raised by the staging load (no operand take, no fetch in flight), is not granted
    // until the EU's next start (the frozen model's io_ir_hold, machine.py: queue.io_held). The
    // reading: on an I/O issue clock the bus unit's request input is the I/O's (its address
    // and the port strobe set up from the EU's port); a line that rises then is first sampled
    // at the next queue event the bus unit watches, the next start's opcode pop (t_start).
    // The hold ends with the start, or when the line falls.
    reg         ioh = 1'b0, fr_prev = 1'b0;
    wire        ioh_set = `V35_MX1G_IOH && req_ack && !rq_mem && l_pop && !take_now
                          && fetch_req && !fr_prev;
    wire        ioh_hold = `V35_MX1G_IOH && ioh && !t_start;
    wire        g_second = free && p2_v;
    wire        b2b_go = free && !g_second && b2b && fetch_req;
    wire        eu_win = free && !g_second && !b2b_go && eu_ok;
    // (Q2) the triple clock's fetch begun and abandoned; (R3) also with the line down a byte
    // short of a word (q_word's second term)
    wire        ab_tri = `V35_Q2_TRI && free && !g_second && !eu_win
                         && (b2b_go || fq_ok || ((`V35_R3_XRW || `V35_R3_ALAT) && !fetch_req))
                         && tri3 && q_word;
    wire        ab_b2b = free && !g_second && b2b && !fetch_req && !eu_ok;
    assign g_abort = ab_tri || ab_b2b;
    assign g_fetch = free && !g_second && !g_abort && !eu_win && (b2b_go || fq_ok);
    assign g_b2b = g_fetch && b2b;
    assign req_ack = eu_win && !g_abort;
    assign g_eu = g_second || req_ack;
    assign g_start = g_eu || g_fetch;
    assign g_kind = g_fetch ? K_FETCH : g_second ? c_kind : rq_kind;
    assign g_addr = g_fetch ? fetch_addr : req_addr;
    assign g_width = !g_eu ? BW_WORD : g_second ? BW_LO : rq_two ? BW_HI
                   : (req_width && (!req_addr[0] || !rq_mem)) ? BW_WORD   // (an I/O word: no pair)
                   : (req_addr[0] ? BW_HI : BW_LO);
    wire [1:0]  g_half = g_second ? 2'd2 : (req_ack && rq_two) ? 2'd1 : 2'd0;
    // the back-to-back sample's hold: an EU request standing at the fetch's last clock
    // (A1_B2BH 1, the rule: req_v or req_resv; 0: req_v only; 2: req_v or a memory cycle's
    // reservation)
    wire        b2b_hold = `A1_B2BH == 0 ? req_v
                         : `A1_B2BH == 1 ? (req_v || req_resv) : (req_v || (req_resv && rq_mem));

    // lengths: bus.length(kind), the SFR store's I/O waits
    wire [1:0] waits_mem = wtc[WTC_MEM_LSB +: 2];
    wire [1:0] waits_io = wtc[WTC_IO_LSB +: 2];
    wire g_sfr = g_kind == K_WRITE && g_addr >= SFR_PAGE;
    assign grant_len = (k_io(g_kind) || g_sfr) ? 3'(BUS_BASE) + 3'(waits_io) :
                       3'(BUS_BASE) + 3'(waits_mem);
    assign fetch_len = 3'(BUS_BASE) + 3'(waits_mem);

    // ------------------------------------------------ (S7b) the ce_b registers
    // the grant (S4), registered at the end of tick A: the end of the clock (the cycle's start,
    // the pins at ce_a) reads these, never tick A's logic
    reg         g_start_b = 1'b0, g_abort_b = 1'b0, g_sfr_b = 1'b0, fetch_req_b = 1'b0;
    reg         b2b_hold_b = 1'b0;
    reg         ioh_set_b = 1'b0, ioh_clr_b = 1'b0;
    reg  [2:0]  g_kind_b = K_NONE, grant_len_b = 3'd0;
    reg  [19:0] g_addr_b = 20'd0;
    reg  [1:0]  g_width_b = BW_WORD, g_half_b = 2'd0;
    always @(posedge clock) begin
        if (!reset_n)
            g_start_b <= 1'b0;       // (the strobes at ce_mid read it before the first ce_b)
        else if (ce_b) begin
            g_start_b <= g_start;
            g_abort_b <= g_abort;
            g_sfr_b <= g_sfr;
            fetch_req_b <= fetch_req;
            b2b_hold_b <= b2b_hold;
            ioh_set_b <= ioh_set;
            ioh_clr_b <= ioh && (t_start || !fetch_req);
            g_kind_b <= g_kind;
            grant_len_b <= grant_len;
            g_addr_b <= g_addr;
            g_width_b <= g_width;
            g_half_b <= g_half;
        end
    end

    // ------------------------------------------------ the end of the clock (S6)
    wire fetch_x = g_start_b && g_kind_b == K_FETCH;
    always @(posedge clock) begin
        if (!reset_n) begin
            c_valid <= 1'b0;
            c_kind <= K_NONE;
            c_pos <= 3'd0;
            c_len <= 3'd0;
            c_internal <= 1'b0;
            c_run <= 1'b0;
            f_since <= 4'd9;
            io_tail <= 2'd0;
            ab_v <= 1'b0;
            ab_pos <= 2'd0;
            d_v <= 1'b0;
            error <= 1'b0;
            // (S7b) the reset complete: the cycle's fields, the delivery's, the write tracker
            c_addr <= 20'd0;
            c_width <= BW_WORD;
            c_half <= 2'd0;
            p2_v <= 1'b0;
            d_kind <= K_NONE;
            d_addr <= 20'd0;
            d_width <= BW_WORD;
            d_p1 <= 1'b0;
            w_v <= 1'b0;
            w_ncyc <= 2'd0;
            w_rel <= 5'sd0;
            b2b <= 1'b0;
            ioh <= 1'b0;
            fr_prev <= 1'b0;
        end else if (ce_a) begin
            fr_prev <= fetch_req_b;
            if (ioh_set_b)
                ioh <= 1'b1;
            else if (ioh_clr_b)
                ioh <= 1'b0;
            // (Q1) the request line sampled at a fetch's last clock, no EU request standing
            b2b <= busy && c_kind == K_FETCH && pos_now == c_len - 3'd1 && fetch_req_b
                   && !b2b_hold_b;
            f_since <= fetch_x ? 4'd0 : fetch_since;
            // (S5a) the last memory write (its last clock relative to the next clock)
            if (g_start_b && g_kind_b == K_WRITE) begin
                w_v <= 1'b1;
                w_ncyc <= 2'd0;
                w_rel <= 5'(grant_len_b) - 5'sd2;
            end else begin
                if (g_start_b && w_ncyc != 2'd3)
                    w_ncyc <= w_ncyc + 2'd1;
                if (w_rel != -5'sd16)
                    w_rel <= w_rel - 5'sd1;
            end
            // the delivery registers: the cycle whose last clock is this one
            d_v <= busy && pos_now == c_len - 3'd1;
            d_kind <= c_kind;
            d_addr <= c_addr;
            d_width <= c_width;
            d_p1 <= c_half == 2'd1;
            if (g_start_b) begin
                if (!free)
                    error <= 1'b1;
                c_valid <= 1'b1;
                c_kind <= g_kind_b;
                c_pos <= 3'd0;
                c_len <= grant_len_b;
                c_internal <= g_sfr_b;
                c_addr <= g_addr_b;
                c_width <= g_width_b;
                c_half <= g_half_b;
                c_run <= fetch_x && fetch_end_prev;
                p2_v <= g_half_b == 2'd1;
            end else begin
                if (busy)
                    c_pos <= pos_now;
                else
                    c_valid <= 1'b0;
            end
            if (g_start_b && k_io(g_kind_b))
                io_tail <= 2'(FIT_IO_RECOVER);
            else if (!(busy && k_io(c_kind)) && io_tail != 2'd0)
                io_tail <= io_tail - 2'd1;
            if (g_abort_b) begin
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
    // (S7b) The pins keep the model's timing while the core's clock sits half a CPU clock later
    // (v35_top: ce_a at the CPU clock's middle, ce_b at its edge). At the edge (ce_e) B1 / B2
    // take the grant tick A has just decided (g_*) and the running cycle's registers as they
    // stood (written at the last ce_a); at the middle (ce_mid, with ce_a) the strobes and the
    // read latch follow the cycle as this clock leaves it (n_*: the registers' next state).
    // The write datum is driven at mid-B2 (Divergence 31): (A1) the EU's req_data as it stands
    // there (the EU holds its issued write's datum through B2, or presents its late result);
    // the bus unit places the pair's bytes (first half: the low byte on the high lane).
    wire        e_valid = g_start || busy;
    wire [2:0]  e_kind = g_start ? g_kind : c_kind;
    wire [2:0]  e_pos = g_start ? 3'd0 : pos_now;
    wire [19:0] e_addr = g_start ? g_addr : c_addr;
    wire [1:0]  e_width = g_start ? g_width : c_width;
    wire        e_internal = g_start ? (g_kind == K_WRITE && g_addr >= SFR_PAGE) : c_internal;
    wire        e_write = e_kind == K_WRITE || e_kind == K_IO_WRITE;
    // the cycle as this clock leaves it (the pins' view from the middle on)
    wire        n_valid = g_start_b || busy;
    wire [2:0]  n_kind = g_start_b ? g_kind_b : c_kind;
    wire [19:0] n_addr = g_start_b ? g_addr_b : c_addr;     // (the function bench's view)
    wire [1:0]  n_width = g_start_b ? g_width_b : c_width;
    wire [2:0]  n_pos = g_start_b ? 3'd0 : pos_now;
    wire [2:0]  n_len = g_start_b ? grant_len_b : c_len;
    wire        n_internal = g_start_b ? g_sfr_b : c_internal;
    wire        n_write = n_kind == K_WRITE || n_kind == K_IO_WRITE;
    wire        pins = n_valid && !n_internal;
    reg  [8:0]  refresh_row = 9'd0;
    // B2's write datum, decided at the edge, driven at the middle
    reg         dp_v = 1'b0;
    reg  [1:0]  dp_half = 2'd0;

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
    end

    always @(posedge clock) begin
        if (!reset_n) begin
            mreq_n <= 1'b1;
            mstb_n <= 1'b1;
            iostb_n <= 1'b1;
            refrq_n <= 1'b1;
            read_write <= 1'b1;
            refresh_row <= 9'd0;
            a0 <= 1'b0;                 // (S7b) the address and data pins too
            a19 <= 1'b0;
            a18_ube <= 1'b0;
            mux_address <= 9'd0;
            data_out <= 16'd0;
            dp_v <= 1'b0;
            dp_half <= 2'd0;
        end else begin
            if (ce_e) begin
                dp_v <= 1'b0;
                if (!e_valid || e_internal) begin
                    read_write <= 1'b1;
                end else if (e_pos == 3'd0) begin
                    // B1: the row (A17..A9), A19, A18 and A0
                    read_write <= !e_write;
                    if (e_kind == K_REFRESH) begin
                        mux_address <= refresh_row;
                        refresh_row <= refresh_row + 1'b1;
                        a0 <= 1'b0;
                        a19 <= 1'b0;
                        a18_ube <= 1'b0;
                    end else begin
                        mux_address <= e_addr[17:9];
                        a0 <= e_addr[0];
                        a19 <= e_addr[19];
                        a18_ube <= e_addr[18];
                    end
                end else if (e_pos == 3'd1 && e_kind != K_REFRESH) begin
                    // B2: the column (A9, A8..A1), /UBE; the write datum at mid-B2
                    mux_address <= {e_addr[9], e_addr[8:1]};
                    a18_ube <= e_width == BW_LO;
                    dp_v <= e_write;
                    dp_half <= c_half;
                end
            end
            if (ce_a && dp_v)
                data_out <= dp_half == 2'd0 ? req_data
                          : dp_half == 2'd1 ? {req_data[7:0], 8'd0} : {8'd0, req_data[15:8]};
            if (ce_mid && pins) begin
                if (n_pos == 3'd0) begin
                    if (n_kind == K_REFRESH)
                        refrq_n <= 1'b0;
                    else
                        mreq_n <= 1'b0;
                end else if (n_pos == n_len - 3'd1) begin
                    mreq_n <= 1'b1;
                    mstb_n <= 1'b1;
                    iostb_n <= 1'b1;
                    refrq_n <= 1'b1;
                end else if (n_kind != K_REFRESH) begin
                    if (k_io(n_kind))
                        iostb_n <= 1'b0;
                    else if (!n_write || n_pos == n_len - 3'd2)
                        mstb_n <= 1'b0;
                end
            end
        end
    end

    // read data: on the pins by mid-B3, delivered on the same CPU clock (the pins' B3 is the
    // core's delivery clock). (S7b) The datum register is written at mid-B3 (ce_mid, with ce_a):
    // the delivery clock's tick A starts from it.
    reg  [15:0] done_r = 16'hffff;
    wire        b3_read = n_valid && n_pos == n_len - 3'd1 && k_read(n_kind) && !n_internal;
    always @(posedge clock) begin
        if (ce_mid && b3_read)
            done_r <= data_in;
    end
    assign done_data = done_r;

    // (S7b) chk begin (generated: the ce_b registers against their sources at ce_a)
`ifndef SYNTHESIS
    /* verilator lint_off BLKSEQ */
    reg chk_on = 1'b0;
    integer chk_n = 0;
    initial chk_on = $test$plusargs("v35_chk");
    always @(posedge clock) begin
        if (chk_on && reset_n && ce_a) begin
            if (g_start_b !== g_start) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: bus.g_start changed in tick B: %h -> %h at %0t",
                             g_start_b, g_start, $time);
            end
            if (g_abort_b !== g_abort) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: bus.g_abort changed in tick B: %h -> %h at %0t",
                             g_abort_b, g_abort, $time);
            end
            if (g_sfr_b !== g_sfr) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: bus.g_sfr changed in tick B: %h -> %h at %0t",
                             g_sfr_b, g_sfr, $time);
            end
            if (fetch_req_b !== fetch_req) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: bus.fetch_req changed in tick B: %h -> %h at %0t",
                             fetch_req_b, fetch_req, $time);
            end
            if (b2b_hold_b !== b2b_hold) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: bus.b2b_hold changed in tick B: %h -> %h at %0t",
                             b2b_hold_b, b2b_hold, $time);
            end
            if (g_kind_b !== g_kind) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: bus.g_kind changed in tick B: %h -> %h at %0t",
                             g_kind_b, g_kind, $time);
            end
            if (grant_len_b !== grant_len) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: bus.grant_len changed in tick B: %h -> %h at %0t",
                             grant_len_b, grant_len, $time);
            end
            if (g_addr_b !== g_addr) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: bus.g_addr changed in tick B: %h -> %h at %0t",
                             g_addr_b, g_addr, $time);
            end
            if (g_width_b !== g_width) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: bus.g_width changed in tick B: %h -> %h at %0t",
                             g_width_b, g_width, $time);
            end
            if (g_half_b !== g_half) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: bus.g_half changed in tick B: %h -> %h at %0t",
                             g_half_b, g_half, $time);
            end
        end
    end
    final if (chk_on && chk_n != 0)
        $display("v35 chk: bus: %0d changes in tick B", chk_n);
    /* verilator lint_on BLKSEQ */
`endif
    // (S7b) chk end
`ifndef SYNTHESIS
    // (A1) +v35_gdbg=FILE: the grant's inputs and its choice per clock (bring-up, classifier)
    integer gdbg = 0, gdbg_t = 0;
    string gdbg_n;
    initial if ($value$plusargs("v35_gdbg=%s", gdbg_n)) gdbg = $fopen(gdbg_n, "w");
    always @(posedge clock) begin
        if (gdbg != 0 && reset_n && ce_a) begin
            $fdisplay(gdbg, "g %0d free%0d rv%0d rr%0d fr%0d ql%0d b2b%0d iw%0d g%0d",
                      gdbg_t, free, req_v, req_resv, fetch_req, q_low, b2b, io_win,
                      g_second ? 5 : g_abort ? 4 : g_fetch ? (b2b ? 1 : 3) : req_ack ? 2 : 0);
            gdbg_t <= gdbg_t + 1;
        end
    end
`endif

    wire unused = &{1'b0, ce_b, wtc[13:2], rfm, 1'(FIT_MIN_GAP), n_addr, n_width};
endmodule
