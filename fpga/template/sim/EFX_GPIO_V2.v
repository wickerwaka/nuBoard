`timescale 1ns/1ps
/* verilator lint_off WIDTHEXPAND */

// Simulation-only stand-in for the Efinix EFX_GPIO_V2 periphery primitive,
// written for Verilator. It follows the vendor model in
// pt/sim_models/verilog/EFX_GPIO_V2.v for the modes this design uses
// (BYPASS, REG and DDIO_RESYNC). Pull options are not modelled; an undriven
// pad reads as 0 in two-state simulation, matching the weak pull-downs.
module EFX_GPIO_V2 #(
    parameter MODE = "INPUT",
    parameter OUT_REG = "BYPASS",
    parameter IN_REG = "BYPASS",
    parameter OE_REG = "BYPASS",
    parameter PULL_OPTION = "NONE",
    parameter IS_OUTCLK_INVERTED = 0,
    parameter IS_INCLK_INVERTED = 0
) (
    output wire [1:0] I,
    output wire       ALT,
    input  wire [1:0] O,
    input  wire       OE,
    input  wire       OUTCLK,
    input  wire       INCLK,
    inout  wire       IO
);
    wire outclk = IS_OUTCLK_INVERTED ? ~OUTCLK : OUTCLK;
    wire inclk = IS_INCLK_INVERTED ? ~INCLK : INCLK;

    reg out0 = 1'b0;
    reg out1_resync = 1'b0;
    reg out1 = 1'b0;
    reg oe_r = 1'b0;
    always @(posedge outclk) begin
        out0 <= O[0];
        out1_resync <= O[1];
        oe_r <= OE;
    end
    always @(negedge outclk)
        out1 <= out1_resync;

    reg in0 = 1'b0;
    reg in1 = 1'b0;
    reg in1_resync = 1'b0;
    always @(posedge inclk) begin
        in0 <= IO;
        in1_resync <= in1;
    end
    always @(negedge inclk)
        in1 <= IO;

    wire out_value =
        OUT_REG == "BYPASS" ? O[0] :
        OUT_REG == "REG"    ? out0 :
                              (outclk ? out0 : out1);
    wire oe_value = OE_REG == "REG" ? oe_r : OE;

    generate
        if (MODE == "OUTPUT")
            assign IO = out_value;
        else if (MODE == "INOUT")
            assign IO = oe_value ? out_value : 1'bz;
    endgenerate

    assign I[0] = IN_REG == "BYPASS" ? IO : in0;
    assign I[1] = in1_resync;
    assign ALT = IO;
endmodule
