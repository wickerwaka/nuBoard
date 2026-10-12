`timescale 1ns/1ps

// HyperRAM I/O layer for the Trion T120. Every HyperBus pin is an EFX_GPIO_V2
// periphery block, so all launch and capture registers sit in the I/O ring and
// the board-level timing is set only by the PLL phases:
//
//   clk_hr      DQ and RWDS outputs. DDIO resync: the HI byte is driven
//               for the first half of each cycle and the LO byte for the second.
//   clk_hr90    CK. Its edges fall in the middle of each DQ half-cycle, which
//               centre-aligns command, address and write data as HyperBus
//               requires.
//   clk_hr_cal  DQ and RWDS inputs. The PLL phase of this clock is a build
//               parameter; the read path does not assume any particular phase.
//
// Input samples are delivered in clk_hr_cal order. In DDIO resync mode the
// falling-edge sample (*_fall) was taken half a cycle before the rising-edge
// sample (*_rise) that accompanies it.
module hyperram_phy (
    input  wire       clk_hr,
    input  wire       clk_hr90,
    input  wire       clk_hr_cal,

    input  wire       cs_n,
    input  wire       ck_en,
    input  wire [7:0] dq_out_hi,
    input  wire [7:0] dq_out_lo,
    input  wire       dq_oe,
    input  wire       rwds_out_hi,
    input  wire       rwds_out_lo,
    input  wire       rwds_oe,

    output wire [7:0] dq_in_fall,
    output wire [7:0] dq_in_rise,
    output wire       rwds_in_fall,
    output wire       rwds_in_rise,

    output wire       hr_ck,
    output wire       hr_cs_n,
    inout  wire       hr_rwds,
    inout  wire [7:0] hr_dq
);
    // ck_en is produced on clk_hr. Retiming it on the falling edge gives the
    // following clk_hr90 rising edge three quarters of a cycle of margin,
    // instead of the quarter cycle a direct clk_hr to clk_hr90 path would get.
    reg ck_en_fall = 1'b0;
    reg ck_en_90 = 1'b0;
    always @(negedge clk_hr)
        ck_en_fall <= ck_en;
    always @(posedge clk_hr90)
        ck_en_90 <= ck_en_fall;

    EFX_GPIO_V2 #(
        .MODE("OUTPUT"),
        .OUT_REG("DDIO_RESYNC")
    ) ck_gpio (
        .I(),
        .ALT(),
        .O({1'b0, ck_en_90}),
        .OE(1'b1),
        .OUTCLK(clk_hr90),
        .INCLK(1'b0),
        .IO(hr_ck)
    );

    // CS# comes from a fabric flip-flop that initialises high, standing in
    // for the output register the other pins have. An I/O-cell register would
    // power up low and select the device before the PLL starts clocking.
    // Routing delay only lengthens tCSH, and at 166 MHz still leaves over
    // 4 ns of the 1.25-cycle tCSS budget against 3 ns.
    reg cs_n_out = 1'b1;
    always @(posedge clk_hr)
        cs_n_out <= cs_n;
    assign hr_cs_n = cs_n_out;

    EFX_GPIO_V2 #(
        .MODE("INOUT"),
        .OUT_REG("DDIO_RESYNC"),
        .IN_REG("DDIO_RESYNC"),
        .OE_REG("REG"),
        .PULL_OPTION("WEAK_PULLDOWN")
    ) rwds_gpio (
        .I({rwds_in_fall, rwds_in_rise}),
        .ALT(),
        .O({rwds_out_lo, rwds_out_hi}),
        .OE(rwds_oe),
        .OUTCLK(clk_hr),
        .INCLK(clk_hr_cal),
        .IO(hr_rwds)
    );

    genvar i;
    generate
        for (i = 0; i < 8; i = i + 1) begin : dq
            EFX_GPIO_V2 #(
                .MODE("INOUT"),
                .OUT_REG("DDIO_RESYNC"),
                .IN_REG("DDIO_RESYNC"),
                .OE_REG("REG"),
                .PULL_OPTION("WEAK_PULLDOWN")
            ) gpio (
                .I({dq_in_fall[i], dq_in_rise[i]}),
                .ALT(),
                .O({dq_out_lo[i], dq_out_hi[i]}),
                .OE(dq_oe),
                .OUTCLK(clk_hr),
                .INCLK(clk_hr_cal),
                .IO(hr_dq[i])
            );
        end
    endgenerate
endmodule
