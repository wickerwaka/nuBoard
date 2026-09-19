`timescale 1ns/1ps

module psram_clock (
    input wire reference_clock,
    input wire startup_clock,
    output wire memory_clock,
    output wire locked
);
`ifdef VERILATOR
    reg simulation_clock = 0;
    always #5 simulation_clock = ~simulation_clock;
    assign memory_clock = simulation_clock;
    assign locked = 1'b1;
`else
    reg [3:0] reset_release = 0;
    wire raw_locked;
    (* async_reg = "true" *) reg [1:0] lock_pipe = 0;
    always @(posedge memory_clock or negedge raw_locked) begin
        if (!raw_locked)
            lock_pipe <= 0;
        else
            lock_pipe <= {lock_pipe[0], 1'b1};
    end
    assign locked = lock_pipe[1];
    always @(posedge startup_clock)
        reset_release <= {reset_release[2:0], 1'b1};

    EFX_PLL_V2 #(
        .N(1), .M(16), .O(2),
        .CLKOUT0_DIV(4),
        .CLKOUT1_DIV(2), .CLKOUT2_DIV(2),
        .CLKOUT0_PHASE(0), .CLKOUT1_PHASE(0), .CLKOUT2_PHASE(0),
        .FEEDBACK_CLK("INTERNAL"), .FEEDBACK_MODE("INTERNAL"),
        .REFCLK_FREQ(50.0)
    ) memory_pll (
        .CLKIN({3'b000, reference_clock}), .CLKSEL(2'b00),
        .RSTN(reset_release[3]), .FBK(1'b0),
        .CLKOUT0(memory_clock), .CLKOUT1(), .CLKOUT2(), .LOCKED(raw_locked)
    );
`endif
endmodule
