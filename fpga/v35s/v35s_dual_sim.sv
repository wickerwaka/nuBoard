`timescale 1ns/1ps

// Simulation-only surrogate for exercising both memory lanes and the
// differential runner: a second model core stands in for the socket. It is
// NOT a real-chip reference.
module v35s_dual_sim (
    input wire clock,
    input wire debug_valid,
    input wire debug_write,
    input wire [19:0] debug_address,
    input wire [15:0] debug_write_data,
    output wire debug_ready,
    output wire debug_error,
    output wire [15:0] debug_read_data
);
    wire a0, a19, a18_ube, mreq_n, mstb_n, iostb_n, read_write, refrq_n;
    wire [8:0] mux_address;
    wire [15:0] data_out, data_in, levels;
    wire ready, reset_n, x1;
    reg previous_x1 = 1'b0;
    always @(posedge clock)
        previous_x1 <= x1;

    v35s_harness #(
        .MODEL_PRESENT(1), .COLD_RESET_TICKS(2000), .POWER_SETTLE_TICKS(100)
    ) harness (
        .clock(clock),
        .debug_valid(debug_valid), .debug_write(debug_write),
        .debug_address(debug_address), .debug_write_data(debug_write_data),
        .debug_ready(debug_ready), .debug_error(debug_error),
        .debug_read_data(debug_read_data),
        .socket_a0(a0), .socket_a19(a19), .socket_a18_ube(a18_ube),
        .socket_mux_address(mux_address), .socket_data_out(data_out),
        .socket_mreq_n(mreq_n), .socket_mstb_n(mstb_n), .socket_iostb_n(iostb_n),
        .socket_read_write(read_write), .socket_refrq_n(refrq_n),
        .socket_p0(8'h00), .socket_p2_out(5'h1f), .socket_r2(4'hf),
        .socket_data_in(data_in), .socket_data_drive(),
        .socket_ready(ready), .socket_reset_n(reset_n),
        .input_levels(levels), .p0_levels(), .port_mode(),
        .socket_armed(), .socket_powered(), .x1(x1),
        .busy(), .complete()
    );

    // The harness edges the model lane on the same X1 the socket sees.
    v35s_model surrogate (
        .clock(clock),
        .x_rise(x1 && !previous_x1),
        .x_fall(!x1 && previous_x1),
        .reset_n(reset_n),
        .ready(ready),
        .data_in(data_in),
        .input_levels(levels),
        .a0(a0), .a19(a19), .a18_ube(a18_ube),
        .mux_address(mux_address), .data_out(data_out),
        .mreq_n(mreq_n), .mstb_n(mstb_n), .iostb_n(iostb_n),
        .read_write(read_write), .refrq_n(refrq_n)
    );
endmodule
