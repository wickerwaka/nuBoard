`timescale 1ns/1ps

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
// (MX5c) It is formed for each value of the queue's line and selected by the line last, and the
// pins' registers load per group from the line's select (README "MX5" round 3).
//
// Clocking: `ce_a` ends a CPU clock; the registers hold the state at the end of the last clock.
// Everything this module outputs is stage S0 (registers only) except the grant, which is S4 and
// is written at the edge. (The trace's and the function bench's views of the bus unit, the
// cycle running and the granted cycle's length, are read from its nets by v35_top's
// observation block: no port carries them.)
//
// Registered state (widths) and the model variables it replaces:
//   c_valid 1, c_kind 3, c_pos 3, c_len 3, c_addr 20, c_width 2, c_half 2, c_internal 1
//                                            bus.current (kind, t - start, length, ...)
//   p2_v 1                                   (A1) the odd word's second half is next
//   dlv_v 1, dlv_kind 3, d_p1 1, done_data 16
//                                            the cycle that ended on t-1 (bus.completed), its
//                                            read datum (latched mid-B3); d_p1: the pair's first
//   io_tail 2                                t <= last_io_end + io_recover
//   ab_v 1, ab_pos 2                         queue.abort_end (the 3-clock aborted fetch cycle:
//                                            nothing on the pins, the bus stays free)
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
    // (F1) the on-chip decision (registers): IDB, PRC.RAMEN; (step B) the on-chip cycle's two
    // targets' read data (registers: the SFR page's, the register RAM's port C)
    input  wire [7:0]  idb,
    input  wire        ramen,
    input  wire [15:0] sfr_rd,
    input  wire [15:0] oc_rd,

    // (A1) the EU's request port (tick A)
    input  wire        req_v,       // a cycle is wanted (a level: stands until acknowledged)
    input  wire [1:0]  req_cyc,     // RQ_MEMR, RQ_MEMW, RQ_IOR, RQ_IOW
    input  wire [19:0] req_addr,    // the cycle's address (the pair's second half's after req_ack)
    input  wire        req_width,   // 1: a word (at an odd address, memory or (F5b) I/O: the bus unit's pair)
    input  wire [15:0] req_data,    // a write's datum, taken at B2 (lane-placed for a byte)
    input  wire        req_resv,    // the reservation: no fetch starts while it is up (unless q_low)
    // (F3b) the request (an RQ_IOR) is an INT acknowledge: the cycle runs as an I/O read with no
    // strobe on the pins and /INTAK low from mid-B1 to mid-B3 (silicon, f3_int: /INTAK low two
    // clocks, no /MREQ, /IOSTB or /MSTB); the read latch takes D7-D0 as for any read
    input  wire        req_ia,
    output reg         intak_n,
    // (F4c) the request is a DMA transfer's cycle: an ordinary memory cycle with `dk` high from
    // mid-B1 to mid-B3 (DMAAK's window: f4_dma, DMAAK low 4.5 clocks of a 5-clock cycle) and
    // `dkt` from mid-B2 for two clocks (TC's: low 2 clocks, inside DMAAK; (F4p) two clocks at
    // 0, 1 and 2 waits alike: validation/v35s/prio.py f4p_dma tc_w0 / tc_w1 / tc_w2)
    input  wire        req_dk,
    output reg         dk,
    output reg         dkt,
    // (F4d) bus hold: HLDRQ as v35_sfr registers it (PMC2 bit 7); /HLDAK (P26). The hold bit
    // (`hold`, a ce_a register) stops every grant but a pair's second half; /HLDAK falls at the
    // pins' edge a clock after the bus went idle under it and rises at the edge after HLDRQ
    // falls, the hold bit staying until then (f4_hold: /HLDAK 1.5 clocks after the cycle in
    // flight ends, 1.5 clocks before the next)
    input  wire        hrq,
    output reg         hlda_n,
    // (F4d) READY: PMC1 bit 7 and the pin's level (v35_sfr's second flop). A memory or I/O
    // cycle on the pins whose WTC field is 3 (2 waits) with PMC1 bit 7 holds its first wait
    // while READY, sampled at the pins' edge (`rdy_q`), is low (f4_rdy rd_on: 160 ticks of the
    // harness's hold after the column strobe add 5 clocks to a read or an I/O cycle, none to a
    // write, whose strobe falls after the first wait's samples)
    input  wire        rdy_en,
    input  wire        rdy_lv,
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

    // S4: the grant, as the queue and the sequencer read it ((step B) the cycle granted, its
    // kind, address and width: this unit's own, the trace's view by name)
    output wire        g_fetch,         // a fetch issued now
    output wire        g_abort,         // the aborted fetch cycle starts now
    output wire        b2b_now,         // (Q1) the line was high at the last clock, a fetch's last

    // S0
    output wire        in_wait,         // bus.in_wait(t)
    output wire        fetch_inflight,  // bus.fetch_inflight(t)
    output wire        fetch_past_b2,   // a fetch past its second clock (start + 2 <= t)
    output wire        cpu_end_prev,    // a non-fetch cycle ended on t-1 (retry_after)
    output wire        dlv_fetch,       // (step B) a fetch ended on t-1: its word is delivered
    output wire [15:0] done_data,       // the read datum of the cycle that ended on t-1 (on the
                                        //   pins mid-B3: (S7b) live through the delivery clock,
                                        //   then latched)
    output wire [15:0] done_nx,         // (F5t) tick B: done_data's next value (the datum register's D)
    output wire        done_ld,         // ... and its load (the register's enable)
    output wire        abort_busy,      // an aborted cycle is in flight (abort_end >= t)
    // (MX5c) the next values of S0 facts (tick B: the state the coming ce_a loads, the D nets
    // of the registers below), for the sequencer's registered stall outcome: nothing new
    output wire        fetch_inflight_nx,
    output wire        fetch_past_b2_nx,
    output wire        in_wait_nx,
    output wire        b2b_now_nx,
    output wire        dlv_fetch_nx,    // (step B) dlv_fetch's
    output wire        eu_done_nx,      // req_done's

    // (F1, step B) the on-chip cycle (below): the SFR page's access port (a store's write at its
    // cycle's end: the enable at ce_a, its condition, the address, width and lane-placed datum;
    // the read: the offset, word, a read cycle's strobe) and the internal RAM's write port (the
    // register RAM's port C: written at the coming ce_b; the EU's segment flops read it too)
    output wire        sfr_wr,
    output wire        sfr_wat,
    output reg  [19:0] sfr_a,
    output reg  [1:0]  sfr_w,
    output wire [15:0] sfr_d,
    output reg  [7:0]  oc_off,
    output reg         oc_word,
    output wire        sfr_rdgo,
    output reg         oc_we,
    output reg  [6:0]  oc_wa,
    output reg  [1:0]  oc_be,
    output reg  [15:0] oc_wd,

    // pins (as v35s_model.sv)
    output wire        a0,
    output wire        a19,
    output wire        a18_ube,
    output wire [8:0]  mux_address,
    output reg  [15:0] data_out,
    output reg         mreq_n,
    output reg         mstb_n,
    output reg         iostb_n,
    output wire        read_write,
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
    reg         c_ia = 1'b0;            // (F3b) the cycle is an INT acknowledge
    reg         g_ia_b = 1'b0;          // (F3b) ... granted now (the ce_b register)
    reg         c_dk = 1'b0;            // (F4c) the cycle is a DMA transfer's
    reg         g_dk_b = 1'b0;          // (F4c) ... granted now (the ce_b register)
    reg         c_rdy = 1'b0;           // (F4d) the cycle waits for READY (WTC field 3, PMC1 bit 7)
    reg         g_rdy_b = 1'b0;         // (F4d) ... granted now (the ce_b register)
    reg         rdy_q = 1'b1;           // (F4d) READY at the pins' last edge (a ce_b register)
    reg         hold = 1'b0;            // (F4d) the bus held: no grant (a ce_a register)
    reg         hold_e = 1'b0;          // (F4d) the hold bit at the pins' last edge (the state
                                        //   boundary that enters the hold)
    reg         hk = 1'b0;              // (F4d) held and idle at the pins' last edge
    reg  [19:0] c_addr = 20'd0;
    reg  [1:0]  c_width = BW_WORD;
    reg  [1:0]  c_half = 2'd0;      // (A1) 0: a cycle of its own, 1: a pair's first, 2: its second
    reg         p2_v = 1'b0;        // (A1) the pair's second half is next
    reg  [1:0]  io_tail = 2'd0;
    reg         ab_v = 1'b0;
    reg  [1:0]  ab_pos = 2'd0;
    reg         d_v = 1'b0;
    reg  [2:0]  d_kind = K_NONE;
    reg         d_p1 = 1'b0;
    reg         b2b = 1'b0;
    assign b2b_now = b2b;

    // ------------------------------------------------ S0
    wire last_clock = c_valid && c_pos == c_len - 3'd1;
    wire busy = c_valid && !last_clock;     // a cycle started on an earlier clock runs on t
    wire [2:0] pos_now = c_pos + 3'd1;
    assign in_wait = busy && !k_io(c_kind) && pos_now >= 3'd2 && pos_now < c_len - 3'd1;
    assign fetch_inflight = busy && c_kind == K_FETCH;
    assign fetch_past_b2 = fetch_inflight && pos_now >= 3'd2;
    wire free = !busy;              // bus.free(t) (min_gap 0; (A1) disp_io=extend's gap clock not built)
    assign cpu_end_prev = d_v && d_kind != K_FETCH;
    assign req_done = cpu_end_prev && !d_p1;
    wire io_win = (busy && k_io(c_kind)) || io_tail != 2'd0;    // t <= last_io_end + io_recover
    assign dlv_fetch = d_v && d_kind == K_FETCH;
    assign abort_busy = ab_v && ab_pos != 2'd2;

    // ------------------------------------------------ S4: the grant (one priority)
    wire [2:0]  rq_kind = req_cyc == RQ_MEMR ? K_READ : req_cyc == RQ_MEMW ? K_WRITE
                        : req_cyc == RQ_IOR ? K_IO_READ : K_IO_WRITE;
    wire        rq_mem = !req_cyc[1];
    // the pair: hi, then lo; (F5b) a word at an odd I/O port too (silicon: two byte cycles)
    wire        rq_two = req_width && req_addr[0];
    // io_recover as the bus unit's turnaround: no EU memory cycle within io_recover clocks of an
    // I/O cycle
    wire        eu_ok = req_v && !(rq_mem && io_win);
    wire        tri3 = t_start && take_now && l_pop;
    // (MX1g) the request line that rises on the clock this unit issues an EU I/O
    // cycle, raised by the staging load (no operand take, no fetch in flight), is not granted
    // until the EU's next start (the frozen model's io_ir_hold, machine.py: queue.io_held). The
    // reading: on an I/O issue clock the bus unit's request input is the I/O's (its address
    // and the port strobe set up from the EU's port); a line that rises then is first sampled
    // at the next queue event the bus unit watches, the next start's opcode pop (t_start).
    // The hold ends with the start, or when the line falls.
    reg         ioh = 1'b0, fr_prev = 1'b0;
    wire        ioh_hold = ioh && !t_start;
    wire        g_second = free && p2_v;
    // (F4d) the grants but the pair's second half need the bus not held (one registered term)
    wire        free_h = free && !hold;
    // (MX5c) the grant expanded on the request line (Shannon's expansion on the bus unit's own
    // input): `gnt_f(fr)` is the priority below with fetch_req = fr, every other input as it
    // stands; the grant is `fetch_req ? gnt_f(1) : gnt_f(0)`, the line selecting last. The bus
    // unit reads nothing it did not read before (the same function; `+v35_chk` compares it with
    // the direct form every clock). README "MX5" round 3
    typedef struct packed {
        logic       start, fetch, abt, ack, sfr, ioh_set, rdy;
        logic [2:0] kind, len;
        logic [1:0] width, half;
    } v35_gnt_t;
    // lengths: bus.length(kind), the SFR store's I/O waits. (F4d) A field of 3 is 2 waits, and
    // READY's with PMC1 bit 7 (f4_rdy rd_off: WTC FFFFh, 5-clock cycles as field 2's)
    wire [1:0] waits_mem = wtc[WTC_MEM_LSB +: 2] == 2'd3 ? 2'd2 : wtc[WTC_MEM_LSB +: 2];
    wire [1:0] waits_io = wtc[WTC_IO_LSB +: 2] == 2'd3 ? 2'd2 : wtc[WTC_IO_LSB +: 2];
    wire       rdy_mem = rdy_en && wtc[WTC_MEM_LSB +: 2] == 2'd3;
    wire       rdy_io = rdy_en && wtc[WTC_IO_LSB +: 2] == 2'd3;
    // (MX5) a write's address is the request's (a write is never a fetch: g_kind K_WRITE implies
    // g_addr = req_addr), so the SFR page's compare reads the request register, not the grant
    // (F1) an on-chip memory cycle: the request's address in the page IDB:E00-FFF (E00-EFF the
    // internal RAM while RAMEN = 1, F00-FFF the SFRs) or FFFFF (IDB at any IDB): read or write,
    // no pins, 3 + the I/O waits (the SFR store's cycle, now every on-chip access's; timing is
    // not F1's). From registers only (the request register, IDB, PRC): an 8-bit compare beside
    // the grant, joining it at the length's select as the old SFR compare did
    wire rq_sfr = (req_addr[19:12] == idb && req_addr[11:9] == 3'b111 && (req_addr[8] || ramen))
                  || req_addr == 20'hFFFFF;
    function automatic v35_gnt_t gnt_f(input logic fr);
        logic fq, b2b_go, eu_win, ab_tri, ab_b2b, eu;
        // rule 3: the queue's low hint overrides a memory cycle's reservation only
        fq = fr && (!req_resv || (q_low && rq_mem)) && !ioh_hold;
        b2b_go = free_h && !g_second && b2b && fr;
        eu_win = free_h && !g_second && !b2b_go && eu_ok;
        // (Q2) the triple clock's fetch begun and abandoned; (R3) also with the line down a byte
        // short of a word (q_word's second term)
        ab_tri = free_h && !g_second && !eu_win && (b2b_go || fq || !fr) && tri3 && q_word;
        ab_b2b = free_h && !g_second && b2b && !fr && !eu_ok;
        gnt_f.abt = ab_tri || ab_b2b;
        gnt_f.fetch = free_h && !g_second && !gnt_f.abt && !eu_win && (b2b_go || fq);
        gnt_f.ack = eu_win && !gnt_f.abt;
        eu = g_second || gnt_f.ack;         // an EU cycle issued now (either half of a pair)
        gnt_f.start = eu || gnt_f.fetch;
        gnt_f.kind = gnt_f.fetch ? K_FETCH : g_second ? c_kind : rq_kind;
        gnt_f.width = !eu ? BW_WORD : g_second ? BW_LO : rq_two ? BW_HI
                    : req_width ? BW_WORD
                    : (req_addr[0] ? BW_HI : BW_LO);
        gnt_f.half = g_second ? 2'd2 : (gnt_f.ack && rq_two) ? 2'd1 : 2'd0;
        gnt_f.sfr = (gnt_f.kind == K_WRITE || gnt_f.kind == K_READ) && rq_sfr;
        gnt_f.len = (k_io(gnt_f.kind) || gnt_f.sfr) ? 3'(BUS_BASE) + 3'(waits_io) :
                    3'(BUS_BASE) + 3'(waits_mem);
        gnt_f.rdy = !gnt_f.sfr && (k_io(gnt_f.kind) ? rdy_io : rdy_mem);
        gnt_f.ioh_set = gnt_f.ack && !rq_mem && l_pop && !take_now && fr && !fr_prev;
    endfunction
    v35_gnt_t gn1, gn0, gn;
    assign gn1 = gnt_f(1'b1);
    assign gn0 = gnt_f(1'b0);
    assign gn = fetch_req ? gn1 : gn0;
    wire        g_start;            // a cycle starts now (a fetch or an EU cycle)
    wire [2:0]  g_kind;
    wire [19:0] g_addr;
    wire [1:0]  g_width;
    assign g_abort = gn.abt;
    assign g_fetch = gn.fetch;
    assign req_ack = gn.ack;
    assign g_start = gn.start;
    assign g_kind = gn.kind;
    assign g_addr = gn.fetch ? fetch_addr : req_addr;
    assign g_width = gn.width;
    wire [1:0]  g_half = gn.half;
    wire        ioh_set = gn.ioh_set;
    // the back-to-back sample's hold: an EU request or reservation standing at the fetch's last
    // clock
    wire        b2b_hold = req_v || req_resv;

    wire g_sfr = gn.sfr;
    wire [2:0] grant_len = gn.len;      // the length of the granted cycle

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
            g_ia_b <= gn.ack && req_ia;     // (F3b) the EU's cycle granted is an acknowledge
            g_dk_b <= gn.ack && req_dk;     // (F4c) ... a DMA transfer's
            g_rdy_b <= gn.rdy;              // (F4d) the cycle granted waits for READY
            rdy_q <= rdy_lv;                // (F4d) READY at the pins' edge
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
    // (F4d) READY's wait: the cycle's first wait (pos 2) repeats while READY was low at the pins'
    // edge that began it (registers only: c_rdy, the position, rdy_q)
    wire        rdy_hold = c_rdy && pos_now == 3'd2 && !rdy_q;
    // (MX5c) the next state the stall reads (the always block below loads exactly these)
    wire        c_valid_nx = g_start_b || busy;
    wire [2:0]  c_kind_nx = g_start_b ? g_kind_b : c_kind;
    wire [2:0]  c_pos_nx = g_start_b ? 3'd0 : busy ? (rdy_hold ? c_pos : pos_now) : c_pos;
    wire [2:0]  c_len_nx = g_start_b ? grant_len_b : c_len;
    wire        busy_nx = c_valid_nx && !(c_pos_nx == c_len_nx - 3'd1);
    wire [2:0]  pos_now_nx = c_pos_nx + 3'd1;
    assign fetch_inflight_nx = busy_nx && c_kind_nx == K_FETCH;
    assign fetch_past_b2_nx = fetch_inflight_nx && pos_now_nx >= 3'd2;
    assign in_wait_nx = busy_nx && !k_io(c_kind_nx) && pos_now_nx >= 3'd2
                        && pos_now_nx < c_len_nx - 3'd1;
    wire        b2b_nx = busy && c_kind == K_FETCH && pos_now == c_len - 3'd1 && fetch_req_b
                         && !b2b_hold_b;
    assign b2b_now_nx = b2b_nx;
    wire        d_v_nx = busy && pos_now == c_len - 3'd1;
    assign dlv_fetch_nx = d_v_nx && c_kind == K_FETCH;
    assign eu_done_nx = d_v_nx && c_kind != K_FETCH && !(c_half == 2'd1);
    always @(posedge clock) begin
        if (!reset_n) begin
            c_valid <= 1'b0;
            c_kind <= K_NONE;
            c_pos <= 3'd0;
            c_len <= 3'd0;
            c_internal <= 1'b0;
            c_ia <= 1'b0;
            c_dk <= 1'b0;
            c_rdy <= 1'b0;
            hold <= 1'b0;
            io_tail <= 2'd0;
            ab_v <= 1'b0;
            ab_pos <= 2'd0;
            d_v <= 1'b0;
            // (S7b) the reset complete: the cycle's fields, the delivery's
            c_addr <= 20'd0;
            c_width <= BW_WORD;
            c_half <= 2'd0;
            p2_v <= 1'b0;
            d_kind <= K_NONE;
            d_p1 <= 1'b0;
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
            b2b <= b2b_nx;
            // the delivery registers: the cycle whose last clock is this one
            d_v <= d_v_nx;
            d_kind <= c_kind;
            d_p1 <= c_half == 2'd1;
            if (g_start_b) begin
                c_valid <= 1'b1;
                c_kind <= g_kind_b;
                c_pos <= 3'd0;
                c_len <= grant_len_b;
                c_internal <= g_sfr_b;
                c_ia <= g_ia_b;
                c_dk <= g_dk_b;
                c_rdy <= g_rdy_b;
                c_addr <= g_addr_b;
                c_width <= g_width_b;
                c_half <= g_half_b;
                p2_v <= g_half_b == 2'd1;
            end else begin
                if (busy)
                    c_pos <= rdy_hold ? c_pos : pos_now;
                else
                    c_valid <= 1'b0;
            end
            // (F4d) the hold bit: HLDRQ, or /HLDAK still low (the bus is taken back a clock
            // after /HLDAK rises)
            hold <= hrq || !hlda_n;
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
    wire        n_ia = g_start_b ? g_ia_b : c_ia;   // (F3b) the cycle on the pins is an acknowledge
    wire        n_dk = g_start_b ? g_dk_b : c_dk;   // (F4c) ... a DMA transfer's
    // (MX5c) the registers the pins' edge writes (ce_e) carry no inferred enable: each loads its
    // group's select every fabric clock, the hold folded into the selected values (below)
    (* syn_extract_enable = "false" *) reg        read_write_r = 1'b1;
    (* syn_extract_enable = "false" *) reg  [8:0] mux_address_r = 9'd0;
    (* syn_extract_enable = "false" *) reg        a0_r = 1'b0, a19_r = 1'b0, a18_ube_r = 1'b0;
    (* syn_extract_enable = "false" *) reg  [8:0] refresh_row = 9'd0;
    // B2's write datum, decided at the edge, driven at the middle
    (* syn_extract_enable = "false" *) reg        dp_v = 1'b0;
    (* syn_extract_enable = "false" *) reg  [1:0] dp_half = 2'd0;
    assign read_write = read_write_r;
    assign mux_address = mux_address_r;
    assign a0 = a0_r;
    assign a19 = a19_r;
    assign a18_ube = a18_ube_r;
    // (MX5c) the pins' edge as a function of the grant: `pin_f(g)` is the B1 / B2 update with the
    // grant g (the e_* view: the cycle granted now, else the running one), the registers' hold
    // values included, so a pin register's only enable is ce_e. Each pin group loads
    // `fetch_req ? pin_f(gn1) : pin_f(gn0)` through its own kept select (syn_keep): the grant's
    // last stage duplicated per group (the request line enters each group's data select, not
    // one grant net with every pin register's enable on it). The same values the update below
    // computed from g_*; README "MX5" round 3
    typedef struct packed {
        logic       rw;
        logic [8:0] ma;
        logic       a0, a19, a18;
        logic [8:0] rr;
        logic       dpv;
        logic [1:0] dph;
    } v35_pin_t;
    /* verilator lint_off UNUSEDSIGNAL */
    function automatic v35_pin_t pin_f(input v35_gnt_t g);
        logic        ev, ein, ew;
        logic [2:0]  ek, ep;
        logic [19:0] ea;
        logic [1:0]  ewd;
        ev = g.start || busy;
        ek = g.start ? g.kind : c_kind;
        ep = g.start ? 3'd0 : pos_now;
        ea = g.start ? (g.fetch ? fetch_addr : req_addr) : c_addr;
        ewd = g.start ? g.width : c_width;
        ein = g.start ? g.sfr : c_internal;
        ew = ek == K_WRITE || ek == K_IO_WRITE;
        pin_f.rw = read_write_r;
        pin_f.ma = mux_address_r;
        pin_f.a0 = a0_r;
        pin_f.a19 = a19_r;
        pin_f.a18 = a18_ube_r;
        pin_f.rr = refresh_row;
        pin_f.dpv = 1'b0;
        pin_f.dph = dp_half;
        if (!ev || ein) begin
            pin_f.rw = 1'b1;
        end else if (ep == 3'd0) begin
            // B1: the row (A17..A9), A19, A18 and A0
            pin_f.rw = !ew;
            if (ek == K_REFRESH) begin
                pin_f.ma = refresh_row;
                pin_f.rr = refresh_row + 1'b1;
                pin_f.a0 = 1'b0;
                pin_f.a19 = 1'b0;
                pin_f.a18 = 1'b0;
            end else begin
                pin_f.ma = ea[17:9];
                pin_f.a0 = ea[0];
                pin_f.a19 = ea[19];
                pin_f.a18 = ea[18];
            end
        end else if (ep == 3'd1 && ek != K_REFRESH) begin
            // B2: the column (A9, A8..A1), /UBE; the write datum at mid-B2
            pin_f.ma = {ea[9], ea[8:1]};
            pin_f.a18 = ewd == BW_LO;
            pin_f.dpv = ew;
            pin_f.dph = c_half;
        end
    endfunction
    /* verilator lint_on UNUSEDSIGNAL */
    // the registers as they stand (the selected values off the edge)
    v35_pin_t pn1, pn0, ph;
    assign ph = {read_write_r, mux_address_r, a0_r, a19_r, a18_ube_r, refresh_row, dp_v, dp_half};
    assign pn1 = ce_e ? pin_f(gn1) : ph;
    assign pn0 = ce_e ? pin_f(gn0) : ph;
    (* syn_keep = "true" *) wire       pk_rw = fetch_req ? pn1.rw : pn0.rw;
    (* syn_keep = "true" *) wire [8:0] pk_ma = fetch_req ? pn1.ma : pn0.ma;
    (* syn_keep = "true" *) wire [2:0] pk_ah = fetch_req ? {pn1.a0, pn1.a19, pn1.a18}
                                                         : {pn0.a0, pn0.a19, pn0.a18};
    (* syn_keep = "true" *) wire [8:0] pk_rr = fetch_req ? pn1.rr : pn0.rr;
    (* syn_keep = "true" *) wire [2:0] pk_dp = fetch_req ? {pn1.dpv, pn1.dph} : {pn0.dpv, pn0.dph};

    initial begin
        data_out = 16'd0;
        mreq_n = 1'b1;
        mstb_n = 1'b1;
        iostb_n = 1'b1;
        refrq_n = 1'b1;
        intak_n = 1'b1;
        dk = 1'b0;
        dkt = 1'b0;
        hlda_n = 1'b1;
    end

    always @(posedge clock) begin
        if (!reset_n) begin
            read_write_r <= 1'b1;
            refresh_row <= 9'd0;
            a0_r <= 1'b0;               // (S7b) the address and data pins too
            a19_r <= 1'b0;
            a18_ube_r <= 1'b0;
            mux_address_r <= 9'd0;
            dp_v <= 1'b0;
            dp_half <= 2'd0;
        end else begin
            read_write_r <= pk_rw;
            mux_address_r <= pk_ma;
            {a0_r, a19_r, a18_ube_r} <= pk_ah;
            refresh_row <= pk_rr;
            {dp_v, dp_half} <= pk_dp;
        end
    end

    always @(posedge clock) begin
        if (!reset_n) begin
            mreq_n <= 1'b1;
            mstb_n <= 1'b1;
            iostb_n <= 1'b1;
            refrq_n <= 1'b1;
            intak_n <= 1'b1;
            dk <= 1'b0;
            dkt <= 1'b0;
            hk <= 1'b0;
            hold_e <= 1'b0;
            hlda_n <= 1'b1;
            data_out <= 16'd0;
        end else begin
            // (F4d) /HLDAK at the pins' edge: low from the second edge with the bus held and idle
            // (no cycle in flight, no pair's second half to come), high at the first edge after
            // HLDRQ falls (registers only)
            if (ce_e) begin
                hold_e <= hold;
                hk <= hold_e && hold && hrq && !busy && !p2_v;
                hlda_n <= !(hk && hold && hrq && !busy && !p2_v);
            end
            // (F4c) a DMA transfer's cycle: DMAAK's and TC's windows
            if (ce_mid) begin
                dk <= pins && n_dk && n_pos != n_len - 3'd1;
                dkt <= pins && n_dk && (n_pos == 3'd1 || n_pos == 3'd2);
            end
            // (F3b) the acknowledge: /INTAK in place of the strobes, mid-B1 to mid-B3
            if (ce_mid && pins && n_ia)
                intak_n <= n_pos == n_len - 3'd1;
            if (ce_a && dp_v)
                data_out <= dp_half == 2'd0 ? req_data
                          : dp_half == 2'd1 ? {req_data[7:0], 8'd0} : {8'd0, req_data[15:8]};
            if (ce_mid && pins && !n_ia) begin
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

    // ------------------------------------------------ (F1) the on-chip cycles
    // (step B: moved in from v35_top; the decision is the grant's own `g_sfr_b`, made once on the
    // request's address: IDB:E00-EFF with RAMEN = 1, IDB:F00-FFF, FFFFF; v35_top made it again
    // on its own ce_b copy of the grant: the same value at every ce_a, IDB and PRC being written
    // at ce_a only) An on-chip memory cycle is captured at its start: its offset (the SFR read's
    // and the register RAM's port C address: both read at every ce_b, this unit latching the
    // datum at the cycle's last clock) and its target. A store is written at its cycle's end
    // with the EU's datum then (a store_imm takes its immediate after the store issued): the SFR
    // page at that ce_a (as the SFR store always was); the internal RAM at the next ce_b (the
    // register RAM's ce_a belongs to the EU's write port), and a write to the current bank's
    // DS0 / SS / DS1 slot updates the segment's flop at the ce_a after (the EU's decode)
    wire        g_top = g_addr_b == 20'hFFFFF;
    wire        g_ocmem = g_start_b && g_sfr_b;
    reg         sfr_open = 1'b0;
    reg         oc_ram = 1'b0;          // the cycle's target: the internal RAM (else the SFRs)
    reg         oc_rdgo = 1'b0;         // (F4b) an on-chip read cycle started at the last ce_a
    initial begin
        sfr_a = 20'd0;
        sfr_w = 2'd0;
        oc_off = 8'd0;
        oc_word = 1'b0;
        oc_we = 1'b0;               // an internal RAM write, landing at the coming ce_b
        oc_wa = 7'd0;
        oc_be = 2'b00;
        oc_wd = 16'd0;
    end
    assign sfr_wr = ce_a && sfr_open && cpu_end_prev && !oc_ram;
    assign sfr_wat = sfr_open && cpu_end_prev && !oc_ram;
    assign sfr_rdgo = oc_rdgo && !oc_ram;
    // the datum by lane: an odd word's halves (a byte cycle of a word request) carry its low
    // byte on the high lane (the first, odd address) and its high byte on the low lane (the
    // second), as this unit places them on the pins (the request's width: the EU port's
    // req_width as it stands at the store's end, as before)
    assign sfr_d = (sfr_w != BW_WORD && req_width) ? {req_data[7:0], req_data[15:8]} : req_data;
    always @(posedge clock) begin
        if (!reset_n) begin
            sfr_open <= 1'b0;
            oc_we <= 1'b0;
        end else if (ce_a) begin
            oc_we <= 1'b0;
            oc_rdgo <= 1'b0;
            // a cycle's end and the next cycle's start can share the clock (an odd word's
            // halves): the end reads the captured cycle, the start captures the new one
            if (sfr_open && cpu_end_prev) begin
                sfr_open <= 1'b0;
                if (oc_ram) begin
                    oc_we <= 1'b1;
                    oc_wa <= sfr_a[7:1];
                    oc_be <= sfr_w == BW_WORD ? 2'b11 : sfr_w == BW_HI ? 2'b10 : 2'b01;
                    oc_wd <= sfr_d;
                end
            end
            if (g_ocmem) begin
                sfr_open <= g_kind_b == K_WRITE;
                oc_rdgo <= g_kind_b == K_READ;
                sfr_a <= g_addr_b;
                sfr_w <= g_width_b;
                oc_off <= g_top ? '1 : g_addr_b[7:0];
                oc_word <= g_width_b == BW_WORD;
                oc_ram <= !g_addr_b[8] && !g_top;
            end
        end
    end
    // the on-chip read's datum: the register RAM's port C or the SFR page, by the cycle's target
    wire [15:0] oc_data = oc_ram ? oc_rd : sfr_rd;

    // read data: on the pins by mid-B3, delivered on the same CPU clock (the pins' B3 is the
    // core's delivery clock). (S7b) The datum register is written at mid-B3 (ce_mid, with ce_a):
    // the delivery clock's tick A starts from it.
    reg  [15:0] done_r = 16'hffff;
    // (F1) an on-chip read's datum at the same point, from the on-chip read register
    wire        b3_read = n_valid && n_pos == n_len - 3'd1 && k_read(n_kind);
    assign done_nx = n_internal ? oc_data : data_in;
    assign done_ld = ce_mid && b3_read;
    always @(posedge clock) begin
        if (done_ld)
            done_r <= done_nx;
    end
    assign done_data = done_r;

    // (S7b) chk begin (generated: the ce_b registers against their sources at ce_a)
`ifndef SYNTHESIS
    // (MX5c) the direct form (the grant as written before the expansion, the pins' edge from it):
    // the reference `+v35_chk` compares the expanded grant and pin_f(gn) with
    wire        x_fq = fetch_req && (!req_resv || (q_low && rq_mem)) && !ioh_hold;
    wire        x_b2b_go = free_h && !g_second && b2b && fetch_req;
    wire        x_eu_win = free_h && !g_second && !x_b2b_go && eu_ok;
    wire        x_ab_tri = free_h && !g_second && !x_eu_win
                           && (x_b2b_go || x_fq || !fetch_req) && tri3 && q_word;
    wire        x_ab_b2b = free_h && !g_second && b2b && !fetch_req && !eu_ok;
    v35_gnt_t   gnt_x;
    logic       x_eu;
    always_comb begin
        gnt_x.abt = x_ab_tri || x_ab_b2b;
        gnt_x.fetch = free_h && !g_second && !gnt_x.abt && !x_eu_win && (x_b2b_go || x_fq);
        gnt_x.ack = x_eu_win && !gnt_x.abt;
        x_eu = g_second || gnt_x.ack;
        gnt_x.start = x_eu || gnt_x.fetch;
        gnt_x.kind = gnt_x.fetch ? K_FETCH : g_second ? c_kind : rq_kind;
        gnt_x.width = !x_eu ? BW_WORD : g_second ? BW_LO : rq_two ? BW_HI
                    : req_width ? BW_WORD
                    : (req_addr[0] ? BW_HI : BW_LO);
        gnt_x.half = g_second ? 2'd2 : (gnt_x.ack && rq_two) ? 2'd1 : 2'd0;
        gnt_x.sfr = (gnt_x.kind == K_WRITE || gnt_x.kind == K_READ) && rq_sfr;
        gnt_x.len = (k_io(gnt_x.kind) || gnt_x.sfr) ? 3'(BUS_BASE) + 3'(waits_io) :
                    3'(BUS_BASE) + 3'(waits_mem);
        gnt_x.rdy = !gnt_x.sfr && (k_io(gnt_x.kind) ? rdy_io : rdy_mem);
        gnt_x.ioh_set = gnt_x.ack && !rq_mem && l_pop && !take_now && fetch_req && !fr_prev;
    end
    // the pins' update from the selected per-group values (what the registers load at ce_e)
    v35_pin_t   pn_x;
    assign pn_x = {pk_rw, pk_ma, pk_ah, pk_rr, pk_dp};
    /* verilator lint_off BLKSEQ */
    reg chk_on = 1'b0;
    integer chk_n = 0;
    initial chk_on = $test$plusargs("v35_chk");
    // (MX5c) every fabric clock: the expanded grant against the direct form, the pins' selected
    // values against the update from it
    always @(posedge clock) begin
        if (chk_on && reset_n && (gn !== gnt_x || pn_x !== (ce_e ? pin_f(gn) : ph))) begin
            chk_n = chk_n + 1;
            if (chk_n <= 20)
                $display("v35 chk: bus: the expanded grant differs from the direct form at %0t",
                         $time);
        end
    end
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
    // diagnostics (+v35_diag): a bus start on a busy bus on stderr (`error`: a start on a bus
    // that was not free, sticky; reported once)
    reg diag = 1'b0;
    reg error = 1'b0, err_seen = 1'b0;
    initial diag = $test$plusargs("v35_diag");
    always @(posedge clock) begin
        if (!reset_n) begin
            error <= 1'b0;
            err_seen <= 1'b0;
        end else if (ce_a) begin
            if (g_start_b && !free)
                error <= 1'b1;
            if (error && !err_seen) begin
                err_seen <= 1'b1;
                if (diag)
                    $display("v35: a bus start on a busy bus");
            end
        end
    end
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
