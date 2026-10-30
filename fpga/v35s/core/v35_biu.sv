`timescale 1ns/1ps

// V35S bus unit (HDL plan, Phase C1), written from the frozen chain model
// (validation/v35s/chains/sim/frozen/bus.py, the BusUnit; machine.py and
// arbiter.py for the clocks it is read and written on) and the spec
// (docs/v35s-chain-rtl-spec.md, A2 "Bus unit", A3 "From the bus unit").
//
// One cycle at a time: B1, B2, waits, B3. A cycle started on model clock s
// with w waits occupies s .. s+2+w; its datum is delivered on clock end+1
// (data_ready=0). Memory cycles and fetches take WTC field 0's waits, I/O
// cycles and the on-chip SFR store field 7's (sfr_cycle=io: the store is
// 3 + the I/O waits and never reaches the pins); a refresh cycle is
// 3 + RFM.RFW clocks (v35_refresh_length).
//
// Clocking. `ce` is the CPU clock (the harness's X1/2 state enable,
// v35s_model.sv's state_start) and marks the END of a model clock: the
// registers below hold the bus unit's state at the end of the last model
// clock (Machine._clock_row's moment). Between two `ce` the combinational
// outputs give the current model clock's values: before the arbiter's choice
// (busy, free, ...) and after it (the _x outputs, with this clock's start).
// The request port is sampled at `ce`, so the arbiter computes its choice
// for clock t during that clock. The pins follow the registered state, so a
// cycle started on model clock s shows B1 on the pins in the CPU state after
// s's `ce`; every edge is in the same place relative to the cycle as in the
// model-lane wrapper (v35s_model.sv's V35 bus engine), whose edge placement
// is ported here: /MREQ (or /REFRQ) falls mid-B1, /IOSTB and a read's /MSTB
// mid-B2, a memory write's /MSTB mid-way through the state before B3, every
// strobe rises mid-B3, where read data is latched.
//
// What the model has and this module keeps: the cycle, the fitted gaps
// (min_gap; disp_io=extend's clock after an I/O cycle, req_ext), the I/O
// recovery window (io_recover, t <= last_io_end + io_recover), the delivery
// clock of a fetch (last_fetch_end == t-1) and the clocks since it (F23's
// flush reads t <= last_fetch_end + fgap), the refresh cycle's length, and the
// data latch (wlatch clocks from a write's issue, a read's delivery, and the
// EU's fills: a register form's last immediate byte, the left-out write's
// slot). What the model does not have is not here: no READY input (WTC mode
// 3 is 3 waits, as machine.waits_of reads it), no per-block WTC fields, no
// internal RAM or IDB-relocated SFR page (only writes at FFF00h and up are
// on-chip), no stall guard (last_cpu_end is a simulation guard). The early
// fetch run of refresh_sync=run (early, early_ok, early_n) is the arbiter's
// bus history (C5, v35_arbiter.sv); rfm_load/rfm_value come from the refresh
// controller (v35_refresh.sv). The refresh row (A17..A9) advances by one, +200h,
// per refresh cycle, as the model numbers its rows (machine.REFRESH_ROW_STEP);
// the row's start is a per-run label in the model (the anchor's), 0 here.
module v35_biu (
    input  wire        clock,
    input  wire        reset_n,
    input  wire        ce,          // end of a model clock (CPU clock enable)
    input  wire        ce_mid,      // the middle of a CPU clock (strobe edges)

    // configuration, from the SFR block
    input  wire [15:0] wtc,
    input  wire [7:0]  rfm,         // RFM at reset: the refresh cycle's length
    input  wire        rfm_load,    // an RFM write takes effect this clock (phase R)
    input  wire [7:0]  rfm_value,

    // request port: the arbiter's choice for this clock (phase X)
    input  wire        req_start,
    input  wire [2:0]  req_kind,    // V35_K_*
    input  wire [19:0] req_addr,
    input  wire [1:0]  req_width,   // V35_BW_*
    input  wire [15:0] req_data,
    input  wire        req_ext,     // disp_io=extend: nothing starts on the clock after its last
    input  wire        req_latch,   // a read whose datum enters the data latch (an EU read)
    input  wire        wlatch_fill, // another datum enters the data latch on this clock

    // delivery: the cycle whose last clock was the previous one (phase C)
    output wire        done,
    output wire [2:0]  done_kind,
    output wire [19:0] done_addr,
    output wire [1:0]  done_width,
    output reg  [15:0] done_data,   // read data, latched mid-B3 (valid from then on)

    // this clock, before the choice
    output wire        busy,
    output wire        free,
    output wire        fetch_inflight,
    output wire        in_wait,
    output wire        fetch_end_prev,  // last_fetch_end == t-1 (a fetch's delivery clock)
    output wire [2:0]  fetch_since,     // t - last_fetch_end (0: a fetch runs, 7: 7 or more)
    output wire        io_win,          // t <= last_io_end + io_recover
    output wire        wlatch_busy,     // the data latch busy (after this clock's delivery)
    output wire [2:0]  cur_kind,        // the cycle on the bus this clock (V35_K_NONE: idle)
    output wire [2:0]  cur_pos,         // t - start
    output wire [2:0]  cur_len,
    // this clock, after the choice (its start included)
    output wire        busy_x,
    output wire        free_x,
    output wire        fetch_inflight_x,
    output wire        in_wait_x,
    output wire        fetch_end_prev_x,
    output wire [2:0]  fetch_since_x,
    output wire        io_win_x,
    output wire        wlatch_busy_x,
    output wire [2:0]  cur_kind_x,
    output wire [2:0]  cur_pos_x,
    output wire [2:0]  cur_len_x,
    output wire [2:0]  start_len,       // the length a start of req_kind would have
    output wire [2:0]  fetch_len,       // bus.length("fetch")
    output wire [2:0]  refresh_len_now, // (C5) bus.length("refresh"), this clock's rfm_load applied
    output reg         error,           // a start on a bus that was not free (sticky)

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
`ifdef V35S_STATE_DUMP
    ,
    // B3 state bundle: the registered state at the end of the last model clock, in the
    // A2 representations (offsets and flags, no clock stamps); the layout is the
    // concatenation at the end of the module, LSB first: c_valid, c_kind, c_pos, c_len,
    // c_ext, c_internal, c_latch, c_addr, c_width, c_data, gap, f_since, io_tail, wl,
    // refresh_len (64 bits under the fit's widths; checked below).
    output wire [63:0] state_dump
`endif
);
`include "v35_chain_params.svh"

    localparam int V35_BIU_STATE_W = 1 + 3 + 3 + 3 + 1 + 1 + 1 + 20 + 2 + 16
                                     + V35_W_GAP + 3 + V35_W_IO_TAIL + V35_W_WLATCH + 3;
`ifdef V35S_STATE_DUMP
    if (V35_BIU_STATE_W != 64) begin : g_state_width
        $error("v35_biu: the state bundle is %0d bits, the port 64", V35_BIU_STATE_W);
    end
`endif

    function automatic bit is_io(input logic [2:0] k);
        is_io = k == V35_K_IO_READ || k == V35_K_IO_WRITE;
    endfunction
    function automatic bit is_read(input logic [2:0] k);
        is_read = k == V35_K_FETCH || k == V35_K_READ || k == V35_K_IO_READ;
    endfunction

    // ------------------------------------------------ registered state (end of clock)
    reg         c_valid = 1'b0;     // a cycle covers the last clock (bus.current)
    reg  [2:0]  c_kind = V35_K_NONE;
    reg  [2:0]  c_pos = 3'd0;       // last clock - start
    reg  [2:0]  c_len = 3'd0;
    reg         c_ext = 1'b0;       // disp_io: last_end = last_io_end = end + 1
    reg         c_internal = 1'b0;  // the SFR store: no pins
    reg         c_latch = 1'b0;     // its read datum enters the data latch
    reg  [19:0] c_addr = 20'd0;
    reg  [1:0]  c_width = V35_BW_WORD;
    reg  [15:0] c_data = 16'd0;
    // max(0, last_end + min_gap - max(t, end)): free once the cycle is over and this is 0
    reg  [V35_W_GAP-1:0] gap = '0;
    // the last fetch: 0 while it runs, else min(7, t - last_fetch_end)
    reg  [2:0]  f_since = 3'd7;
    // max(0, last_io_end + io_recover - max(t, end)) for the last I/O cycle
    reg  [V35_W_IO_TAIL-1:0] io_tail = '0;
    // max(0, wlatch_until - t): the data latch's clocks left
    reg  [V35_W_WLATCH-1:0] wl = '0;
    reg  [2:0]  refresh_len = 3'd0;

    // ------------------------------------------------ this clock, before the choice
    wire last_clock = c_valid && c_pos == c_len - 3'd1;
    assign done = last_clock;
    assign done_kind = c_kind;
    assign done_addr = c_addr;
    assign done_width = c_width;
    assign busy = c_valid && !last_clock;
    wire [2:0] pos_now = c_pos + 3'd1;
    assign cur_kind = busy ? c_kind : V35_K_NONE;
    assign cur_pos = busy ? pos_now : 3'd0;
    assign cur_len = busy ? c_len : 3'd0;
    assign in_wait = busy && !is_io(c_kind) && pos_now >= 3'd2 && pos_now < c_len - 3'd1;
    assign fetch_inflight = busy && c_kind == V35_K_FETCH;
    assign free = !busy && gap == '0;
    assign fetch_since = fetch_inflight ? 3'd0 : (f_since == 3'd7 ? 3'd7 : f_since + 3'd1);
    assign fetch_end_prev = fetch_since == 3'd1;
    assign io_win = (busy && is_io(c_kind)) || io_tail != '0;

    // the data latch: a read's datum on its delivery clock, a write from its issue
    wire [V35_W_WLATCH-1:0] wl_now = wl == '0 ? '0 : wl - 1'b1;
    wire fill_c = last_clock && c_latch && (c_kind == V35_K_READ || c_kind == V35_K_IO_READ);
    wire fill_x = (req_start && req_kind == V35_K_WRITE) || wlatch_fill;
    wire [V35_W_WLATCH-1:0] wl_fill = wl_now > V35_W_WLATCH'(FIT_WLATCH) ? wl_now : V35_W_WLATCH'(FIT_WLATCH);
    wire [V35_W_WLATCH-1:0] wl_c = fill_c ? wl_fill : wl_now;
    wire [V35_W_WLATCH-1:0] wl_x = (fill_c || fill_x) ? wl_fill : wl_now;
    assign wlatch_busy = wl_c != '0;
    assign wlatch_busy_x = wl_x != '0;

    // lengths: bus.length(kind), the SFR store's I/O waits
    wire [2:0] rl_now = rfm_load ? v35_refresh_length(rfm_value) : refresh_len;
    wire [1:0] waits_mem = wtc[V35_WTC_MEM_LSB +: 2];
    wire [1:0] waits_io = wtc[V35_WTC_IO_LSB +: 2];
    wire req_sfr = req_kind == V35_K_WRITE && req_addr >= V35_SFR_PAGE;
    assign start_len = req_kind == V35_K_REFRESH ? rl_now :
                       (is_io(req_kind) || req_sfr) ? 3'(V35_BUS_BASE) + waits_io :
                       3'(V35_BUS_BASE) + waits_mem;
    assign fetch_len = 3'(V35_BUS_BASE) + waits_mem;
    assign refresh_len_now = rl_now;

    // ------------------------------------------------ after the choice
    assign busy_x = busy || req_start;
    assign free_x = free && !req_start;
    assign fetch_inflight_x = req_start ? req_kind == V35_K_FETCH : fetch_inflight;
    assign in_wait_x = req_start ? 1'b0 : in_wait;            // a start's clock is its B1
    assign fetch_since_x = req_start && req_kind == V35_K_FETCH ? 3'd0 : fetch_since;
    assign fetch_end_prev_x = fetch_since_x == 3'd1;
    assign io_win_x = io_win || (req_start && is_io(req_kind));
    assign cur_kind_x = req_start ? req_kind : cur_kind;
    assign cur_pos_x = req_start ? 3'd0 : cur_pos;
    assign cur_len_x = req_start ? start_len : cur_len;

    // ------------------------------------------------ the end of the clock
    always @(posedge clock) begin
        if (!reset_n) begin
            c_valid <= 1'b0;
            c_kind <= V35_K_NONE;
            c_pos <= 3'd0;
            c_len <= 3'd0;
            c_ext <= 1'b0;
            c_internal <= 1'b0;
            c_latch <= 1'b0;
            gap <= '0;
            f_since <= 3'd7;        // last_fetch_end = -10: stale
            io_tail <= '0;
            wl <= '0;
            refresh_len <= v35_refresh_length(rfm);
            error <= 1'b0;
        end else if (ce) begin
            refresh_len <= rl_now;
            wl <= wl_x;
            f_since <= fetch_since_x;
            if (req_start) begin
                if (!free)
                    error <= 1'b1;
                c_valid <= 1'b1;
                c_kind <= req_kind;
                c_pos <= 3'd0;
                c_len <= start_len;
                c_ext <= req_ext;
                c_internal <= req_sfr;
                c_latch <= req_latch;
                c_addr <= req_addr;
                c_width <= req_width;
                c_data <= req_data;
                gap <= V35_W_GAP'(FIT_MIN_GAP + (req_ext ? V35_DISP_IO_EXT : 0));
            end else begin
                if (busy)
                    c_pos <= pos_now;
                else
                    c_valid <= 1'b0;    // completed (or idle)
                if (!busy && gap != '0)
                    gap <= gap - 1'b1;
            end
            if (req_start && is_io(req_kind))
                io_tail <= V35_W_IO_TAIL'(FIT_IO_RECOVER + (req_ext ? V35_DISP_IO_EXT : 0));
            else if (!(busy && is_io(c_kind)) && io_tail != '0)
                io_tail <= io_tail - 1'b1;
        end
    end

    // ------------------------------------------------ pins
    // The state the registers take at this `ce`: the CPU state that starts now.
    wire        n_valid = req_start || busy;
    wire [2:0]  n_kind = req_start ? req_kind : c_kind;
    wire [2:0]  n_pos = req_start ? 3'd0 : pos_now;
    wire [19:0] n_addr = req_start ? req_addr : c_addr;
    wire [1:0]  n_width = req_start ? req_width : c_width;
    wire [15:0] n_data = req_start ? req_data : c_data;
    wire        n_internal = req_start ? req_sfr : c_internal;
    wire        n_write = n_kind == V35_K_WRITE || n_kind == V35_K_IO_WRITE;
    wire        c_write = c_kind == V35_K_WRITE || c_kind == V35_K_IO_WRITE;
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
                if (n_kind == V35_K_REFRESH) begin
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
            end else if (n_pos == 3'd1 && n_kind != V35_K_REFRESH) begin
                // B2: the column (A9, A8..A1), /UBE, the write data
                mux_address <= {n_addr[9], n_addr[8:1]};
                a18_ube <= n_width == V35_BW_LO;
                if (n_write)
                    data_out <= n_data;
            end
        end else if (ce_mid && pins) begin
            if (c_pos == 3'd0) begin
                if (c_kind == V35_K_REFRESH)
                    refrq_n <= 1'b0;
                else
                    mreq_n <= 1'b0;
            end else if (c_pos == c_len - 3'd1) begin
                mreq_n <= 1'b1;
                mstb_n <= 1'b1;
                iostb_n <= 1'b1;
                refrq_n <= 1'b1;
            end else if (c_kind != V35_K_REFRESH) begin
                if (is_io(c_kind))
                    iostb_n <= 1'b0;
                else if (!c_write || c_pos == c_len - 3'd2)
                    mstb_n <= 1'b0;
            end
        end
    end

    // read data: latched mid-B3, delivered on the next model clock
    always @(posedge clock) begin
        if (ce_mid && c_valid && c_pos == c_len - 3'd1 && is_read(c_kind) && !c_internal)
            done_data <= data_in;
    end

`ifdef V35S_STATE_DUMP
    assign state_dump = {refresh_len, wl, io_tail, f_since, gap, c_data, c_width, c_addr,
                         c_latch, c_internal, c_ext, c_len, c_pos, c_kind, c_valid};
`endif
endmodule
