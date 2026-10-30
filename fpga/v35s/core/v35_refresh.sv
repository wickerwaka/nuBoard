`timescale 1ns/1ps

// V35S refresh controller (HDL plan, Phase C5), written from the frozen chain model
// (validation/v35s/chains/sim/frozen/refresh.py, the Refresh; machine.py for the phase R it
// runs in, arbiter.py and eu.py for its readers and writers) and the spec
// (docs/v35s-chain-rtl-spec.md, A2 "Refresh", A3 "From the refresh controller").
//
// The timer is a free-running 7-bit counter (refresh_counter=edge): a refresh request is the
// rising edge of its bit RFT + 3 (refresh_interval=16: 16 << RFT clocks a period), sampled every
// clock against the previous clock's selected bit (a write of RFT that selects a bit already
// high while the old one was low raises a request at once), raised only with RFEN set and none
// pending (a period elapsing meanwhile is not counted twice). `pending` is set in phase R and
// cleared when the arbiter starts the refresh cycle (phase X, Refresh.start). An RFM store (the
// EU's SFR write, issued in X) takes effect rfm_delay clocks after its issue, in that clock's R
// (refresh_on_write): RFEN, RFT and, through the bus unit's rfm_load/rfm_value, the refresh
// cycle's length RFW; clearing RFEN drops a pending request. refresh_restart=free: the counter
// runs on whatever RFM holds (the model's `due` timer is dead under refresh_counter=edge).
//
// `en`: the chain runs the controller at all (frozen machine.py builds the Refresh only for a
// chain with refresh on at some point, types.refresh_any: from the prelude's RFM or after an RFM
// store); without it nothing here is read and no RFM store reaches the bus unit. The counter's
// value at the model's clock 0 (the prelude's POP PSW read, prelude_anchor=pop) is an input
// (`init_counter`, refresh.POP_COUNTER for the run's prelude), as the queue's preload is.
// Not built: the prelude cut-off `enable_at` (0 under prelude_anchor=pop), `due`/`timer`
// (refresh_timer=grid is inert under refresh_counter=edge), the logs `served` and `writes`.
//
// Clocking. `ce` marks the END of a model clock: the registers hold the controller's state at
// the end of the last model clock. Phase R is combinational from them (`pending`, `rfm_load`,
// `rfm_value`, `state_r`); the clock's X inputs (`start`, `wr`) give the end-of-clock state.
module v35_refresh #(
    parameter int STATE_W = 24              // $bits(v35_rst_t), checked below
) (
    input  wire        clock,
    input  wire        reset_n,
    input  wire        ce,                  // end of a model clock

    input  wire        en,                  // the chain runs the controller (refresh_any)
    input  wire [7:0]  rfm,                 // the prelude's RFM (RFEN, RFT at the start)
    input  wire [6:0]  init_counter,        // the counter at the model's clock 0

    // phase X
    input  wire        start,               // the arbiter starts the refresh cycle
    input  wire        wr,                  // the EU's RFM store issued ...
    input  wire [7:0]  wr_value,            // ... with this value

    // phase R
    output wire        pending,             // a refresh request is pending (the arbiter's)
    output wire        rfm_load,            // an RFM write takes effect (the bus unit's RFW)
    output wire [7:0]  rfm_value,
    output wire [STATE_W-1:0] state_r,      // after R
    output wire [STATE_W-1:0] state_e       // the end of the clock
`ifdef V35S_STATE_DUMP
    ,
    output wire [STATE_W-1:0] state_dump    // as registered at the last ce
`endif
);
`include "v35_chain_params.svh"

    // the counter bit of the half interval: refresh_interval = 16 << RFT, bit 3 + RFT
    localparam int BIT0 = $clog2(FIT_REFRESH_INTERVAL) - 1;

    // the state (rtl_vectors.RFFIELDS, MSB first)
    typedef struct packed {
        logic [6:0] counter;        // (c0 + t) mod 128, the clock just ended
        logic       prev_v;         // prev_bit is set (not on clock 0) ...
        logic       prev_bit;       // ... the selected bit on the last clock
        logic [1:0] rft;            // RFM.RFT
        logic       on;             // RFM.RFEN
        logic       pending;        // a request is pending
        logic       wv;             // an RFM store waits to take effect ...
        logic [1:0] w_off;          // ... at t + w_off (write_at - t)
        logic [7:0] w_value;        // ... with this value
    } v35_rst_t;

    if ($bits(v35_rst_t) != STATE_W) begin : g_state_width
        $error("v35_refresh: the state is %0d bits, STATE_W %0d", $bits(v35_rst_t), STATE_W);
    end
    if (BIT0 + 3 > 6 || (1 << (BIT0 + 1)) != FIT_REFRESH_INTERVAL
            || FIT_RFM_DELAY < 1 || FIT_RFM_DELAY > 3) begin : g_fit
        $error("v35_refresh: refresh_interval or rfm_delay out of the controller's range");
    end

    v35_rst_t r;                            // the end of the last model clock
    v35_rst_t s_r, s_e;
    logic     load;
    logic [7:0] lval;

    always_comb begin
        v35_rst_t s;
        logic bit_, rise;
        s = r;
        load = 1'b0;
        lval = 8'd0;
        s.counter = r.counter + 7'd1;
        if (s.wv) begin
            s.w_off = r.w_off - 2'd1;
            if (s.w_off == 2'd0 && en) begin
                // Refresh._apply: RFEN, RFT, the bus unit's RFW (rfm_load)
                load = 1'b1;
                lval = r.w_value;
                s.on = v35_refresh_on(r.w_value);
                s.rft = r.w_value[1:0];
                if (!s.on)
                    s.pending = 1'b0;
                s.wv = 1'b0;
                s.w_off = 2'd0;
                s.w_value = 8'd0;
            end
        end
        // Refresh.raise_ (refresh_counter=edge)
        bit_ = s.counter[BIT0 + int'(s.rft)];
        rise = bit_ && s.prev_v && !s.prev_bit;
        s.prev_v = 1'b1;
        s.prev_bit = bit_;
        if (rise && s.on && en && !s.pending)
            s.pending = 1'b1;
        s_r = s;
    end

    // phase X: Refresh.start, Refresh.write (a process of its own: X reads phase R)
    always_comb begin
        v35_rst_t s;
        s = s_r;
        if (start)
            s.pending = 1'b0;
        if (wr && en) begin
            s.wv = 1'b1;
            s.w_off = 2'(FIT_RFM_DELAY);
            s.w_value = wr_value;
        end
        s_e = s;
    end

    assign pending = s_r.pending;
    assign rfm_load = load;
    assign rfm_value = lval;
    assign state_r = s_r;
    assign state_e = s_e;

    always @(posedge clock) begin
        if (!reset_n) begin
            r <= '0;
            r.counter <= init_counter - 7'd1;
            r.rft <= rfm[1:0];
            r.on <= en && v35_refresh_on(rfm);
        end else if (ce) begin
            r <= s_e;
        end
    end

`ifdef V35S_STATE_DUMP
    assign state_dump = r;
`endif
endmodule
