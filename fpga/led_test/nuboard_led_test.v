`timescale 1ns/1ps

// Rear bank-LED diagnostic.
//
// Each bank has a red/green indicator driven by a 74LVC1G139 decoder:
//
//   OE_N = 1              both LEDs off
//   OE_N = 0, DIR = 0     red LED on
//   OE_N = 0, DIR = 1     green LED on
//
// The test visits T0..T2, B0..B2, L0..L2, then R0..R2. Each bank
// spends half a second in each state: off, red, green. Only the control
// pins are exercised; the 96 bank data pins remain high impedance.
module nuboard_led_test (
    input  wire        clk_50mhz,
    input  wire        clk_50mhz_alias,
    output wire        heartbeat_out,

    output wire        spi_miso,
    input  wire        spi_cs_n,
    input  wire        spi_sck,
    input  wire        spi_mosi,
    output wire        fpga_irq_n,

    output wire        dut_isolate,
    output wire        dut_crowbar,
    output wire        psram_ce_n,
    output wire        psram_sclk,
    output wire        psram_si,
    input  wire        psram_so,
    output wire        psram_sio2,
    output wire        psram_sio3,

    inout  wire [7:0]  t0,
    inout  wire [7:0]  t1,
    inout  wire [7:0]  t2,
    output wire        t0_dir,
    output wire        t1_dir,
    output wire        t2_dir,
    output wire        t0_oe_n,
    output wire        t1_oe_n,
    output wire        t2_oe_n,

    inout  wire [7:0]  b0,
    inout  wire [7:0]  b1,
    inout  wire [7:0]  b2,
    output wire        b0_dir,
    output wire        b1_dir,
    output wire        b2_dir,
    output wire        b0_oe_n,
    output wire        b1_oe_n,
    output wire        b2_oe_n,

    inout  wire [7:0]  l0,
    inout  wire [7:0]  l1,
    inout  wire [7:0]  l2,
    output wire        l0_dir,
    output wire        l1_dir,
    output wire        l2_dir,
    output wire        l0_oe_n,
    output wire        l1_oe_n,
    output wire        l2_oe_n,

    inout  wire [7:0]  r0,
    inout  wire [7:0]  r1,
    inout  wire [7:0]  r2,
    output wire        r0_dir,
    output wire        r1_dir,
    output wire        r2_dir,
    output wire        r0_oe_n,
    output wire        r1_oe_n,
    output wire        r2_oe_n,

    inout  wire        tx,
    inout  wire        ty,
    inout  wire        bx,
    inout  wire        by,
    inout  wire        lx,
    inout  wire        ly,
    inout  wire        rx,
    inout  wire        ry,
    output wire        xy_oe_n,

    output wire        tclk,
    output wire        tclk_en,
    output wire        bclk,
    output wire        bclk_en,
    output wire        lclk,
    output wire        lclk_en,
    output wire        rclk,
    output wire        rclk_en
);
    localparam [24:0] HALF_SECOND_CYCLES = 25'd25_000_000;

    localparam [1:0] PHASE_OFF   = 2'd0;
    localparam [1:0] PHASE_RED   = 2'd1;
    localparam [1:0] PHASE_GREEN = 2'd2;

    reg [24:0] phase_count = 25'd0;
    reg [3:0]  bank_index = 4'd0;
    reg [1:0]  phase = PHASE_OFF;

    always @(posedge clk_50mhz) begin
        if (phase_count == HALF_SECOND_CYCLES - 1) begin
            phase_count <= 25'd0;

            if (phase == PHASE_GREEN) begin
                phase <= PHASE_OFF;

                if (bank_index == 4'd11)
                    bank_index <= 4'd0;
                else
                    bank_index <= bank_index + 1'b1;
            end else begin
                phase <= phase + 1'b1;
            end
        end else begin
            phase_count <= phase_count + 1'b1;
        end
    end

    reg [11:0] bank_dir;
    reg [11:0] bank_oe_n;

    always @* begin
        bank_dir = 12'b0000_0000_0000;
        bank_oe_n = 12'b1111_1111_1111;

        if (phase != PHASE_OFF) begin
            bank_oe_n[bank_index] = 1'b0;
            bank_dir[bank_index] = phase == PHASE_GREEN;
        end
    end

    // Bank vector order is T0, T1, T2, B0, B1, B2, L0, L1, L2,
    // R0, R1, R2 from bit zero through bit eleven.
    assign t0_dir = bank_dir[0];
    assign t1_dir = bank_dir[1];
    assign t2_dir = bank_dir[2];
    assign b0_dir = bank_dir[3];
    assign b1_dir = bank_dir[4];
    assign b2_dir = bank_dir[5];
    assign l0_dir = bank_dir[6];
    assign l1_dir = bank_dir[7];
    assign l2_dir = bank_dir[8];
    assign r0_dir = bank_dir[9];
    assign r1_dir = bank_dir[10];
    assign r2_dir = bank_dir[11];

    assign t0_oe_n = bank_oe_n[0];
    assign t1_oe_n = bank_oe_n[1];
    assign t2_oe_n = bank_oe_n[2];
    assign b0_oe_n = bank_oe_n[3];
    assign b1_oe_n = bank_oe_n[4];
    assign b2_oe_n = bank_oe_n[5];
    assign l0_oe_n = bank_oe_n[6];
    assign l1_oe_n = bank_oe_n[7];
    assign l2_oe_n = bank_oe_n[8];
    assign r0_oe_n = bank_oe_n[9];
    assign r1_oe_n = bank_oe_n[10];
    assign r2_oe_n = bank_oe_n[11];

    // Preserve the input half of every undriven package inout at this wrapper
    // boundary. Efinity otherwise removes the port before applying the ISF.
    (* syn_keep = "true" *)
    wire [103:0] dut_input_sample = {
        t0,
        t1,
        t2,
        b0,
        b1,
        b2,
        l0,
        l1,
        l2,
        r0,
        r1,
        r2,
        tx,
        ty,
        bx,
        by,
        lx,
        ly,
        rx,
        ry
    };

    // The normal template supplies the MCU mailbox, heartbeat, PSRAM test,
    // sideband defaults, and all board-level safety outputs. Its bank-control
    // outputs are intentionally left on private wires and replaced above.
    wire unused_t0_dir;
    wire unused_t1_dir;
    wire unused_t2_dir;
    wire unused_t0_oe_n;
    wire unused_t1_oe_n;
    wire unused_t2_oe_n;
    wire unused_b0_dir;
    wire unused_b1_dir;
    wire unused_b2_dir;
    wire unused_b0_oe_n;
    wire unused_b1_oe_n;
    wire unused_b2_oe_n;
    wire unused_l0_dir;
    wire unused_l1_dir;
    wire unused_l2_dir;
    wire unused_l0_oe_n;
    wire unused_l1_oe_n;
    wire unused_l2_oe_n;
    wire unused_r0_dir;
    wire unused_r1_dir;
    wire unused_r2_dir;
    wire unused_r0_oe_n;
    wire unused_r1_oe_n;
    wire unused_r2_oe_n;

    nuboard_template runtime (
        .clk_50mhz(clk_50mhz),
        .clk_50mhz_alias(clk_50mhz_alias),
        .heartbeat_out(heartbeat_out),
        .spi_miso(spi_miso),
        .spi_cs_n(spi_cs_n),
        .spi_sck(spi_sck),
        .spi_mosi(spi_mosi),
        .fpga_irq_n(fpga_irq_n),
        .dut_isolate(dut_isolate),
        .dut_crowbar(dut_crowbar),
        .psram_ce_n(psram_ce_n),
        .psram_sclk(psram_sclk),
        .psram_si(psram_si),
        .psram_so(psram_so),
        .psram_sio2(psram_sio2),
        .psram_sio3(psram_sio3),

        .t0(t0),
        .t1(t1),
        .t2(t2),
        .t0_dir(unused_t0_dir),
        .t1_dir(unused_t1_dir),
        .t2_dir(unused_t2_dir),
        .t0_oe_n(unused_t0_oe_n),
        .t1_oe_n(unused_t1_oe_n),
        .t2_oe_n(unused_t2_oe_n),

        .b0(b0),
        .b1(b1),
        .b2(b2),
        .b0_dir(unused_b0_dir),
        .b1_dir(unused_b1_dir),
        .b2_dir(unused_b2_dir),
        .b0_oe_n(unused_b0_oe_n),
        .b1_oe_n(unused_b1_oe_n),
        .b2_oe_n(unused_b2_oe_n),

        .l0(l0),
        .l1(l1),
        .l2(l2),
        .l0_dir(unused_l0_dir),
        .l1_dir(unused_l1_dir),
        .l2_dir(unused_l2_dir),
        .l0_oe_n(unused_l0_oe_n),
        .l1_oe_n(unused_l1_oe_n),
        .l2_oe_n(unused_l2_oe_n),

        .r0(r0),
        .r1(r1),
        .r2(r2),
        .r0_dir(unused_r0_dir),
        .r1_dir(unused_r1_dir),
        .r2_dir(unused_r2_dir),
        .r0_oe_n(unused_r0_oe_n),
        .r1_oe_n(unused_r1_oe_n),
        .r2_oe_n(unused_r2_oe_n),

        .tx(tx),
        .ty(ty),
        .bx(bx),
        .by(by),
        .lx(lx),
        .ly(ly),
        .rx(rx),
        .ry(ry),
        .xy_oe_n(xy_oe_n),

        .tclk(tclk),
        .tclk_en(tclk_en),
        .bclk(bclk),
        .bclk_en(bclk_en),
        .lclk(lclk),
        .lclk_en(lclk_en),
        .rclk(rclk),
        .rclk_en(rclk_en)
    );
endmodule
