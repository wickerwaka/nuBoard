`timescale 1ns/1ps

// (S7b) The timing wrapper of one V35S core v2 module (fpga/v35s/synth/v35_timing.sh): the
// module's inputs come from a shift chain clocked by the one clock (so every input path starts
// at a register, as inside the core), each output bit is registered (so every output path ends
// at one), and the output registers are XOR-folded into eight pins: a module with hundreds of
// ports fits the T120F484's I/O, and nothing it computes is optimised away. The timing the
// place-and-route reports is then the module's own register-to-register timing, plus the
// paths from its inputs to its registers and from its outputs' logic to the output registers
// (as the whole core sees them from a neighbour's registers).
//
// v35_timing.sh generates the wrapper's top (v35_tw_top, the module's ports cut from the chain
// and onto the folds) from the module's port list; these are its two halves.

// the input chain: q[0] the newest bit
module v35_tw_in #(
    parameter int N = 2
) (
    input  wire         clock,
    input  wire         si,
    output reg  [N-1:0] q
);
    initial q = '0;
    always @(posedge clock)
        q <= {q[N-2:0], si};
endmodule

// the output registers and their fold onto eight pins
module v35_tw_out #(
    parameter int N = 1
) (
    input  wire         clock,
    input  wire [N-1:0] d,
    output reg  [7:0]   xo
);
    reg [N-1:0] r = '0;
    logic [7:0] f;
    always_comb begin
        f = 8'd0;
        for (int i = 0; i < N; i++)
            f[i % 8] = f[i % 8] ^ r[i];
    end
    always @(posedge clock) begin
        r <= d;
        xo <= f;
    end
    initial xo = 8'd0;
endmodule
