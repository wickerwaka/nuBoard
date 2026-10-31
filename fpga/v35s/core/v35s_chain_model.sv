`timescale 1ns/1ps

// V35S model lane, second core (HDL plan, Phase D3 and the start of C6; WP82): the chain-model
// core (v35_chain_core.sv, built with V35S_CHAIN_LANE) running free from /RESET, with the same
// ports as v35s_model.sv (the ucore lane) so v35s_harness.sv instantiates either.
//
// Nothing is scripted: the core fetches the reset vector and runs the image's prelude itself;
// every fetch, data and I/O cycle is a bus cycle on the lane, and the data the core uses is the
// data its own cycles latched at B3 (the bus unit's done_data). What this wrapper adds:
//
//   * The clock. One CPU clock (one bus state) per CLKOUT = X1 / 2, 4 or 8 by PRC.PCK, X1/8 at
//     reset until the prelude's PRC store; a PCK change takes effect at the next state boundary
//     (the ucore wrapper's divider). The core ends a model clock at the start of a state
//     (`run`, once its clock's chain has settled) and places its strobes on the middle
//     (`ce_mid`). A model clock that has not settled by the next state's start is an error
//     (`unsettled`; the core bench's worst case is 6 settle edges, a state at fX/2 has 8).
//   * The reset exit (not modelled by the chain model: the measured A3 figures as parameters).
//     docs/v35s-bus-timing.md "Reset" and docs/v35s-core-decision.md "Reset exit (A3)": the
//     first bus activity is a refresh 118-128 X1 periods after /RESET rises (about 15.5 fX/8
//     states, /REFRQ falling mid-B1), the first fetch, from FFFF0, at 198-208 X1 periods
//     (about 25.5 states); the spread is the fX/8 divider's phase at release, which here
//     starts at release. So the refresh's B1 is state RESET_REFRESH_STATE (15) and the first
//     fetch's B1 state RESET_FETCH_STATE (25): the core is held in reset until then (its first
//     model clock the state before the fetch's B1, a cycle started on model clock s being on
//     the pins from the next state), and this wrapper drives the one refresh cycle before it
//     (RFM's reset RFW: 2 waits, 5 states; row 0). The core's refresh counter then continues
//     that refresh's grid (16 clocks a period at RFT 0): init_counter below.
//   * The SFR block (v35_sfr.sv): PRC, WTC, RFM, IDB, written by the core's SFR stores (the
//     model's internal 3 + I/O-wait cycle, sfr_cycle=io) at the store cycle's end; WTC and RFM
//     to the core, PRC.PCK to the divider. The internal routing is the chain model's: data
//     writes at FFF00h and up (the SFR page for IDB = FFh) are on-chip and never reach the pins;
//     everything else, the stack at 0E00h-0F00h included, goes to the bus. The internal RAM
//     (IDB:E00-EFF with PRC.RAMEN) is not built: PRC 4Ch sets RAMEN, but with IDB = FFh that RAM
//     is FFE00-FFEFF, which no chain touches, so RAMEN changes nothing here (the corpus shows
//     the stack on the bus, as it is).
//   * refresh_on (the chain model's refresh_any: whether the core runs its refresh controller
//     and the refresh templates) is RFM.RFEN of the SFR block, live: on from reset, cleared or
//     kept by the prelude's RFM store. A chain that turns refresh on later with its own RFM
//     store (F17) runs without it until that store (the model runs it from clock 0).
//   * The code cache: the bytes of the core's own fetches (4 KiB direct-mapped by A11..A0,
//     tagged A19..A12), from which the core's code window and its late-immediate window read
//     with a valid bit per byte (v35_eu.sv: a start waits for its bytes; a memory form's
//     trailing immediate may come after its start). A fetch delivered on a clock is visible to
//     that clock's starts (the queue receives it in phase C).
//   * The prelude's POP PSW: the core issues its read (v35_chain_core.sv pop_fire) on the first
//     clock the EU waits for it with the bus free, entering the chain model's clock-0 state.
//
// Diagnostics (+chain_diag): the reset exit, the POP PSW fire clock, each stall of a start for
// unfetched bytes after the POP read, core errors and unsettled clocks go to stderr.
module v35s_chain_model
    import v35_decoder_pkg::*;
    import v35_eu_pkg::*;
#(
    parameter int RESET_REFRESH_STATE = 15,     // A3: first refresh 118-128 X1 (/REFRQ mid-B1)
    parameter int RESET_FETCH_STATE = 25        // A3: first fetch 198-208 X1 (/MREQ mid-B1)
) (
    input  wire        clock,
    input  wire        x_rise,
    input  wire        x_fall,
    input  wire        reset_n,
    input  wire        ready,
    input  wire [15:0] data_in,
    input  wire [15:0] input_levels,
    output reg         a0,
    output reg         a19,
    output reg         a18_ube,
    output reg  [8:0]  mux_address,
    output reg  [15:0] data_out,
    output reg         mreq_n,
    output reg         mstb_n,
    output reg         iostb_n,
    output reg         read_write,
    output reg         refrq_n
);
    localparam int STATE_W = 1021;

    // ---------------------------------------------------------------- SFRs
    wire [7:0] prc, rfm, idb;
    wire [15:0] wtc;
    reg sfr_wr = 1'b0;
    reg [19:0] sfr_a = 20'd0;
    reg [1:0] sfr_w = 2'd0;
    reg [15:0] sfr_d = 16'd0;
    v35_sfr sfr (.clock, .reset_n, .wr(sfr_wr), .addr(sfr_a), .width(sfr_w), .data(sfr_d),
                 .prc, .wtc, .rfm, .idb);

    // ---------------------------------------------------------- CPU clock
    // As v35s_model.sv's divider, restarted at /RESET so the reset exit is in whole states.
    reg [2:0] x_count = 3'd0;
    reg [1:0] pck = 2'd2;
    wire [2:0] x_last = pck == 2'd0 ? 3'd1 : pck == 2'd1 ? 3'd3 : 3'd7;
    wire [2:0] x_mid = pck == 2'd0 ? 3'd1 : pck == 2'd1 ? 3'd2 : 3'd4;
    wire state_start = reset_n && x_rise && x_count == 3'd0;
    wire state_mid = reset_n && x_rise && x_count == x_mid;
    always @(posedge clock) begin
        if (!reset_n) begin
            x_count <= 3'd0;
            pck <= 2'd2;
        end else if (x_rise) begin
            if (x_count == x_last)
                x_count <= 3'd0;
            else
                x_count <= x_count + 1'b1;
            if (x_count == 3'd0)
                pck <= prc[1:0];
        end
    end

    // ---------------------------------------------------------- the reset exit
    // states since /RESET rose (the first state after release is 0), saturating
    reg [5:0] state_n = 6'd0;
    reg started = 1'b0;             // a state has begun since release
    always @(posedge clock) begin
        if (!reset_n) begin
            state_n <= 6'd0;
            started <= 1'b0;
        end else if (state_start) begin
            started <= 1'b1;
            if (started && state_n != 6'd63)
                state_n <= state_n + 1'b1;
        end
    end
    // the state now (valid once started)
    wire [5:0] state_now = started ? state_n : 6'd0;
    // the core leaves reset at the start of the state before the fetch's B1
    reg core_run = 1'b0;
    always @(posedge clock) begin
        if (!reset_n)
            core_run <= 1'b0;
        else if (state_start && started && state_n + 6'd1 == 6'(RESET_FETCH_STATE - 1))
            core_run <= 1'b1;
    end
    wire core_reset_n = reset_n && core_run;

    // the reset-exit refresh: B1 in state RESET_REFRESH_STATE, 3 + RFW(reset) states
    localparam int RX_LEN = 5;      // RFM FCh: RFW 3 as 2 (v35_refresh_length)
    reg rx_refrq_n = 1'b1;
    always @(posedge clock) begin
        if (!reset_n)
            rx_refrq_n <= 1'b1;
        else if (state_mid && !core_run) begin
            if (state_now == 6'(RESET_REFRESH_STATE))
                rx_refrq_n <= 1'b0;
            else if (state_now == 6'(RESET_REFRESH_STATE + RX_LEN - 1))
                rx_refrq_n <= 1'b1;
        end
    end
    // the core's refresh counter at its clock 0 (the state RESET_FETCH_STATE - 1): the reset
    // refresh's request was raised on the clock before its B1 (RESET_REFRESH_STATE - 1), at a
    // rise of the counter's bit 3 (refresh_interval=16: value 8)
    localparam int INIT_COUNTER = (8 + (RESET_FETCH_STATE - 1) - (RESET_REFRESH_STATE - 1)) % 128;

    // ---------------------------------------------------------- the code cache
    localparam int CW = 12;
    reg [7:0] cache_byte [0:(1 << CW) - 1];
    reg [7:0] cache_tag [0:(1 << CW) - 1];
    reg       cache_v [0:(1 << CW) - 1];
    integer ci;
    initial begin
        for (ci = 0; ci < (1 << CW); ci = ci + 1) begin
            cache_byte[ci] = 8'h00;
            cache_tag[ci] = 8'h00;
            cache_v[ci] = 1'b0;
        end
    end

    // ---------------------------------------------------------- the core
    wire        run = state_start && core_run;
    wire        settled, done, error, pop_fire, sfr_issue;
    wire        lane_stall, lane_late, lane_start, lane_spec, lane_spec_bad;
    wire [1:0]  n_start, done_width, sfr_width;
    wire [2:0]  done_kind;
    wire [19:0] done_addr, code_addr, fetch_addr, lx_addr, sfr_addr;
    wire [15:0] done_data, sfr_data;
    wire [7:0]  err_code;
    logic [95:0] code_win;
    logic [11:0] code_ok;
    logic [47:0] lx_win;
    logic [5:0]  lx_ok;
    wire c_a0, c_a19, c_a18_ube, c_mreq_n, c_mstb_n, c_iostb_n, c_read_write, c_refrq_n;
    wire [8:0] c_mux_address;
    wire [15:0] c_data_out;

    // the start state: Machine.__init__'s idle EU (no instruction, the class none, the
    // decoder's take address the first fetch's), the reset registers: PS FFFFh and IP 0 (pc,
    // code_org 0), the reset vector FFFF0h where the lane sees the first fetch (the data book's
    // PS FFFFh, PC 0000h; not F000h:0000h, which is F0000h), PSW F002h (MD 1, RB 7, BRKI as the
    // chain prelude's POP leaves it; the other flags clear), the rest 0; the queue empty, its
    // first fetch at FFFF0h
    v35_st_t init_s;
    always_comb begin
        init_s = '0;
        init_s.d.taddr = 20'hFFFF0;
        init_s.d.ra_off = 1;
        init_s.e.cls = CLS_NONE;
        init_s.e.ccls = CLS_NONE;
        init_s.e.prev_cls = CLS_NONE;
        init_s.e.res = 1;
        init_s.e.op_len = 3'd1;
        init_s.e.wbu = 2'd1;
        init_s.e.lu_off = 3'd1;
        init_s.e.cs_now = 1'b1;
        init_s.f.ps = 16'hFFFF;
        init_s.f.psw = 16'hF002;
    end

    v35_chain_core core (
        .clock, .reset_n(core_reset_n), .run, .ce_mid(state_mid),
        .init_state(STATE_W'(init_s)), .code_org(16'd0), .init_count(4'd0), .init_data(64'd0),
        .init_fetch_addr(20'hFFFF0), .wtc, .rfm, .refresh_on(rfm[4]),
        .init_counter(7'(INIT_COUNTER)),
        .code_addr, .code_win, .fetch_addr, .fetch_data(16'd0), .data_in,
        .settled, .n_start, .done, .done_kind, .done_addr, .error, .err_code,
        .a0(c_a0), .a19(c_a19), .a18_ube(c_a18_ube), .mux_address(c_mux_address),
        .data_out(c_data_out), .mreq_n(c_mreq_n), .mstb_n(c_mstb_n), .iostb_n(c_iostb_n),
        .read_write(c_read_write), .refrq_n(c_refrq_n),
        .done_data_o(done_data), .done_width_o(done_width), .code_ok, .lx_addr, .lx_win,
        .lx_ok, .sfr_issue, .sfr_addr, .sfr_width, .sfr_data, .pop_fire, .lane_stall,
        .lane_late, .lane_spec, .lane_spec_bad, .lane_start
    );

    // the code windows: the cache, with the fetch delivered this clock (phase C) bypassed in
    wire fetch_now = done && done_kind == V35_K_FETCH;
    function automatic logic [8:0] byte_at(input logic [19:0] a);   // {valid, byte}
        logic [CW-1:0] i;
        i = a[CW-1:0];
        if (fetch_now && done_width == V35_BW_WORD && a[19:1] == done_addr[19:1])
            byte_at = {1'b1, a[0] ? done_data[15:8] : done_data[7:0]};
        else if (fetch_now && done_width != V35_BW_WORD && a == done_addr)
            byte_at = {1'b1, done_width == V35_BW_HI ? done_data[15:8] : done_data[7:0]};
        else
            byte_at = {cache_v[i] && cache_tag[i] == a[19:CW], cache_byte[i]};
    endfunction
    always_comb begin
        logic [8:0] b;
        for (int k = 0; k < 12; k++) begin
            b = byte_at(code_addr + 20'(k));
            code_win[95 - 8 * k -: 8] = b[7:0];
            code_ok[11 - k] = b[8];
        end
        for (int k = 0; k < 6; k++) begin
            b = byte_at(lx_addr + 20'(k));
            lx_win[47 - 8 * k -: 8] = b[7:0];
            lx_ok[5 - k] = b[8];
        end
    end

    wire commit = run && settled;
    reg reset_prev = 1'b0;
    always @(posedge clock) begin
        reset_prev <= reset_n;
        if (!reset_n) begin
            if (reset_prev)                 // emptied once, on entering reset
                for (ci = 0; ci < (1 << CW); ci = ci + 1)
                    cache_v[ci] <= 1'b0;
        end else if (commit && fetch_now) begin
            if (done_width == V35_BW_WORD) begin
                cache_byte[{done_addr[CW-1:1], 1'b0}] <= done_data[7:0];
                cache_tag[{done_addr[CW-1:1], 1'b0}] <= done_addr[19:CW];
                cache_v[{done_addr[CW-1:1], 1'b0}] <= 1'b1;
                cache_byte[{done_addr[CW-1:1], 1'b1}] <= done_data[15:8];
                cache_tag[{done_addr[CW-1:1], 1'b1}] <= done_addr[19:CW];
                cache_v[{done_addr[CW-1:1], 1'b1}] <= 1'b1;
            end else begin
                cache_byte[done_addr[CW-1:0]] <= done_width == V35_BW_HI ? done_data[15:8]
                                                                          : done_data[7:0];
                cache_tag[done_addr[CW-1:0]] <= done_addr[19:CW];
                cache_v[done_addr[CW-1:0]] <= 1'b1;
            end
        end
    end

    // the SFR store: captured at its issue, written at its cycle's end
    reg sfr_open = 1'b0;
    always @(posedge clock) begin
        sfr_wr <= 1'b0;
        if (!core_reset_n) begin
            sfr_open <= 1'b0;
        end else if (commit) begin
            if (sfr_issue) begin
                sfr_open <= 1'b1;
                sfr_a <= sfr_addr;
                sfr_w <= sfr_width;
                sfr_d <= sfr_data;
            end else if (sfr_open && done) begin
                sfr_open <= 1'b0;
                sfr_wr <= 1'b1;
            end
        end
    end

    // ---------------------------------------------------------- pins
    always @* begin
        a0 = c_a0;
        a19 = c_a19;
        a18_ube = c_a18_ube;
        mux_address = c_mux_address;
        data_out = c_data_out;
        mreq_n = c_mreq_n;
        mstb_n = c_mstb_n;
        iostb_n = c_iostb_n;
        read_write = c_read_write;
        refrq_n = c_refrq_n;
        if (!core_run) begin
            a0 = 1'b0;
            a19 = 1'b0;
            a18_ube = 1'b0;
            mux_address = 9'd0;
            mreq_n = 1'b1;
            mstb_n = 1'b1;
            iostb_n = 1'b1;
            read_write = 1'b1;
            refrq_n = rx_refrq_n;
        end
    end

    // ---------------------------------------------------------- diagnostics
    reg diag = 1'b0;
    reg error_seen = 1'b0;
    reg pop_seen = 1'b0;
    reg [31:0] clock_n = 32'd0;     // the core's model clocks
    initial diag = $test$plusargs("chain_diag");
    always @(posedge clock) begin
        if (!core_reset_n) begin
            clock_n <= 32'd0;
            error_seen <= 1'b0;
            pop_seen <= 1'b0;
        end else if (run) begin
            if (!settled && diag)
                $display("chain-lane: model clock %0d did not settle", clock_n);
            if (commit) begin
                clock_n <= clock_n + 1'b1;
                if (pop_fire) begin
                    pop_seen <= 1'b1;
                    if (diag)
                        $display("chain-lane: POP PSW read at model clock %0d (state %0d)",
                                 clock_n, clock_n + RESET_FETCH_STATE - 1);
                end
                if (lane_stall && pop_seen && diag)
                    $display("chain-lane: a start held for unfetched bytes at model clock %0d",
                             clock_n);
                if (lane_spec && pop_seen && diag)
                    $display("chain-lane: a start with its ModR/M byte to come at model clock %0d",
                             clock_n);
                if (lane_spec_bad && !error_seen && diag)
                    $display("chain-lane: an assumed ModR/M byte changed the format (clock %0d)",
                             clock_n);
                if (lane_late && diag)
                    $display("chain-lane: an EU cycle with late bytes missing at clock %0d",
                             clock_n);
                if ((error || err_code != 8'd0 || lane_spec_bad) && !error_seen) begin
                    error_seen <= 1'b1;
                    if (diag)
                        $display("chain-lane: core error %02x at model clock %0d", err_code,
                                 clock_n);
                end
            end
        end
    end
endmodule
