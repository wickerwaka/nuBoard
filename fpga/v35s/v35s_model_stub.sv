`timescale 1ns/1ps

// Placeholder model lane: an idle bus. The harness is built with
// MODEL_PRESENT=0 when this file is used, so model runs are rejected.
module v35s_model (
    input  wire        clock,
    input  wire        x_rise,
    input  wire        x_fall,
    input  wire        reset_n,
    input  wire        ready,
    input  wire [15:0] data_in,
    input  wire [15:0] input_levels,
    output wire        a0,
    output wire        a19,
    output wire        a18_ube,
    output wire [8:0]  mux_address,
    output wire [15:0] data_out,
    output wire        mreq_n,
    output wire        mstb_n,
    output wire        iostb_n,
    output wire        read_write,
    output wire        refrq_n
);
    assign a0 = 1'b0;
    assign a19 = 1'b0;
    assign a18_ube = 1'b1;
    assign mux_address = 9'd0;
    assign data_out = 16'd0;
    assign mreq_n = 1'b1;
    assign mstb_n = 1'b1;
    assign iostb_n = 1'b1;
    assign read_write = 1'b1;
    assign refrq_n = 1'b1;
endmodule
