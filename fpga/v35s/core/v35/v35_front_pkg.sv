`timescale 1ns/1ps

// V35S core v2, front end (stage S2 of docs/v35s-core-v2.md): the bus-cycle kinds and widths,
// the fitted constants the front end reads, and the request rule's room as one function the
// queue evaluates at each stage that reads it.
//
// The constants are the tracked fit's (validation/v35s/chains/fit.json, md5
// de193740eaf1dee0862d2220ae084909, fit 62), copied by hand for S2; S1's generated
// v35_consts.svh / v35_class_tbl.svh replace them (the names below are the fit's).
package v35_front_pkg;

    // ------------------------------------------------------------ bus cycle kinds and widths
    // (the same encodings as the old core's v35_chain_params.svh, so v35_sfr.sv reads them)
    localparam logic [2:0] K_NONE = 3'd0;
    localparam logic [2:0] K_FETCH = 3'd1;
    localparam logic [2:0] K_READ = 3'd2;
    localparam logic [2:0] K_WRITE = 3'd3;
    localparam logic [2:0] K_IO_READ = 3'd4;
    localparam logic [2:0] K_IO_WRITE = 3'd5;
    localparam logic [2:0] K_REFRESH = 3'd6;
    localparam logic [1:0] BW_WORD = 2'd0;
    localparam logic [1:0] BW_LO = 2'd1;
    localparam logic [1:0] BW_HI = 2'd2;

    function automatic logic k_io(input logic [2:0] k);
        k_io = k == K_IO_READ || k == K_IO_WRITE;
    endfunction
    function automatic logic k_read(input logic [2:0] k);
        k_read = k == K_FETCH || k == K_READ || k == K_IO_READ;
    endfunction

    // ------------------------------------------------------------ the EU's request record
    // (as posted: arbiter.Request's fields the S2 rules read)
    typedef struct packed {
        logic [2:0]  kind;
        logic [19:0] addr;
        logic [1:0]  width;
        logic [15:0] data;
        logic [6:0]  setup;
        logic        fn_v;      // free_need is set (None: every setup clock fetch-free)
        logic [2:0]  fn;        // free_need
        logic [1:0]  lead;
        logic        port;      // an I/O form with a port byte
        logic        detached;  // io_release=post
        logic        grp;       // grp_free_bus
    } req_t;

    // ------------------------------------------------------------ fixed structure
    localparam int QUEUE_BYTES = 6;             // queue.QUEUE_BYTES
    localparam int BUS_BASE = 3;                // bus.BASE: B1 B2 B3
    localparam logic [19:0] SFR_PAGE = 20'hFFF00;   // eu.SFR_PAGE: an on-chip store
    localparam int WTC_MEM_LSB = 0;             // machine.waits_of: WTC field 0 (memory, fetch)
    localparam int WTC_IO_LSB = 14;             // ... field 7 (I/O, the SFR store)

    // ------------------------------------------------------------ fit integers (fit.json)
    localparam int FIT_HOLD_Q = 3;              // hold_q
    localparam int FIT_IO_RECOVER = 2;          // io_recover
    localparam int FIT_WLATCH = 4;              // wlatch
    localparam int FIT_MIN_GAP = 0;             // min_gap

    // ------------------------------------------------------------ the request rule's room
    // queue.room(t) under the fit (room_ir=arrival_idle, word_latch=byte_d, latch_midtake,
    // latch_disp, room_ir_imm=none, modrm_mate=imm, release=byte, take_commit=at_end):
    //   used  = len(bytes) + uncommitted + 2·inflight − (the latched byte, when it is
    //           uncounted: on its delivery clock while the decoder holds the write port, and
    //           neither mid-take nor on a displacement's take clock)
    //   size  = 6, +1 with the IR as a seventh slot (a delivery clock, or no operand bytes
    //           outstanding unless a two-byte-immediate register form runs), `used` counting
    //           the IR byte then; ir_hold takes the slot away (its `used += ir` branch)
    //   used += 1 on a delivery clock that took the ModR/M's word-mate (modrm_mate=imm)
    // Signed: −4 .. 7.
    function automatic logic signed [4:0] room_f(
        input logic [3:0] cnt,          // len(bytes): stored + latched
        input logic [2:0] unc,          // taken, not committed
        input logic       inflight,     // a word in flight (or an aborted cycle)
        input logic       lat,          // the latched byte is present
        input logic       arrived_now,  // a word was delivered on this clock
        input logic       port_busy,    // the decoder holds the write port on this clock
        input logic       need_nz,      // operand bytes outstanding (mid-take)
        input logic       disp_now,     // a displacement's take on this clock (latch_disp)
        input logic       ir_v,         // the IR holds an opcode
        input logic       imm16,        // a two-byte-immediate register form runs (room_ir_imm)
        input logic       ir_hold,      // ir_load=disp_data: the IR is no seventh slot
        input logic       mate_now      // the ModR/M's word-mate taken on a delivery clock
    );
        logic signed [5:0] used, size;
        logic lat_now;
        used = 6'(cnt) + 6'(unc) + (inflight ? 6'sd2 : 6'sd0);
        // _latched_now (byte_d): the byte counts as a queue byte after its delivery clock,
        // and on it unless the decoder holds the port
        lat_now = lat && arrived_now && port_busy;
        if (lat_now && !need_nz && !disp_now)
            used = used - 6'sd1;
        size = 6'sd6;
        if (arrived_now || (!need_nz && !imm16)) begin
            if (ir_hold && !need_nz)
                used = used + (ir_v ? 6'sd1 : 6'sd0);
            else begin
                size = size + 6'sd1;
                used = used + (ir_v ? 6'sd1 : 6'sd0);
            end
        end
        if (arrived_now && mate_now)
            used = used + 6'sd1;
        room_f = 5'(size - used);
    endfunction

endpackage
