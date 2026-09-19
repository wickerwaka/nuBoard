`timescale 1ns/1ps

module nuboard_m68000 (
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
    inout  wire        psram_si,
    inout  wire        psram_so,
    inout  wire        psram_sio2,
    inout  wire        psram_sio3,

    // Each edge has three independent eight-bit bidirectional banks. The
    // group and bit indices match the board net names: t2[3] is F_T23.
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

    // The TXS0108 provides automatic direction sensing for these sideband
    // signals, so the eight lines share one enable and have no DIR pins.
    inout  wire        tx,
    inout  wire        ty,
    inout  wire        bx,
    inout  wire        by,
    inout  wire        lx,
    inout  wire        ly,
    inout  wire        rx,
    inout  wire        ry,
    output wire        xy_oe_n,

    // Each edge clock has a dedicated signal and external-buffer enable.
    output wire        tclk,
    output wire        tclk_en,
    output wire        bclk,
    output wire        bclk_en,
    output wire        lclk,
    output wire        lclk_en,
    output wire        rclk,
    output wire        rclk_en
);

    wire input_valid, input_ready, input_last;
    wire output_valid, output_ready, output_last;
    wire [7:0] input_data, output_data;
    wire debug_valid, debug_write, debug_ready, debug_error;
    wire [19:0] debug_address;
    wire [15:0] debug_write_data, debug_read_data;
    wire armed, cpu_clock, reset_pull, halt_pull;
    wire [15:0] cpu_data_in;
    wire dtack_n, berr_n;
    // Capture uses only BRAM. Keep the external memory deselected and quiet.
    assign psram_ce_n = 1'b1;
    assign psram_sclk = 1'b0;
    assign psram_si = 1'bz;
    assign psram_so = 1'bz;
    assign psram_sio2 = 1'bz;
    assign psram_sio3 = 1'bz;

    nuboard_mailbox mailbox_link (
        .clk_50mhz(clk_50mhz),
        .heartbeat_out(heartbeat_out),
        .spi_miso(spi_miso),
        .spi_cs_n(spi_cs_n),
        .spi_sck(spi_sck),
        .spi_mosi(spi_mosi),
        .fpga_irq_n(fpga_irq_n),
        .application_input_valid(input_valid),
        .application_input_ready(input_ready),
        .application_input_data(input_data),
        .application_input_last(input_last),
        .application_output_valid(output_valid),
        .application_output_ready(output_ready),
        .application_output_data(output_data),
        .application_output_last(output_last)
    );

    nuboard_debug_bridge bridge (
        .clock(clk_50mhz),
        .input_valid(input_valid),
        .input_ready(input_ready),
        .input_data(input_data),
        .input_last(input_last),
        .output_valid(output_valid),
        .output_ready(output_ready),
        .output_data(output_data),
        .output_last(output_last),
        .debug_valid(debug_valid),
        .debug_write(debug_write),
        .debug_address(debug_address),
        .debug_write_data(debug_write_data),
        .debug_ready(debug_ready),
        .debug_error(debug_error),
        .debug_read_data(debug_read_data)
    );

    // Pin ordering comes from hardware/68000 U1 pad nets, not connector order.
    wire [23:0] cpu_address = {
        b2[6:0], b0[4], b0[5], b0[6], b0[7],
        b1[0], b1[1], b1[2], b1[3], b1[4], b1[5], b1[6], b1[7],
        b0[3:0], 1'b0
    };
    wire [15:0] cpu_data_out = {
        t0[0], t0[1], t0[2], t0[3], t0[4], t0[5], t0[6], t0[7],
        t1[2], t1[1], t1[0], t1[7], t1[6], t1[5], t1[4], t1[3]
    };

    m68000_harness harness (
        .clock(clk_50mhz),
        .debug_valid(debug_valid),
        .debug_write(debug_write),
        .debug_address(debug_address),
        .debug_write_data(debug_write_data),
        .debug_ready(debug_ready),
        .debug_error(debug_error),
        .debug_read_data(debug_read_data),
        .socket_address(cpu_address),
        .socket_data_out(cpu_data_out),
        .socket_as_n(l0[0]),
        .socket_uds_n(l0[1]),
        .socket_lds_n(l0[2]),
        .socket_read(l0[3]),
        .socket_fc({l2[0], l2[1], l2[2]}),
        .socket_reset_n(ly),
        .socket_halt_n(lx),
        .socket_data_in(cpu_data_in),
        .socket_data_drive(),
        .socket_dtack_n(dtack_n),
        .socket_berr_n(berr_n),
        .socket_armed(armed),
        .socket_reset_pull(reset_pull),
        .socket_halt_pull(halt_pull),
        .cpu_clock(cpu_clock),
        .busy(),
        .complete()
    );

    // Keep driving throughout reads, including gaps between bus strobes.
    // Only R/W changes the direction while armed; AS, UDS/LDS, and responder
    // readiness do not gate the external DIR or FPGA output enables.
    wire want_drive = armed && l0[3];
    assign t0 = want_drive ? {
        cpu_data_in[8], cpu_data_in[9], cpu_data_in[10], cpu_data_in[11],
        cpu_data_in[12], cpu_data_in[13], cpu_data_in[14], cpu_data_in[15]
    } : 8'hzz;
    assign t1 = want_drive ? {
        cpu_data_in[4], cpu_data_in[3], cpu_data_in[2], cpu_data_in[1],
        cpu_data_in[0], cpu_data_in[7], cpu_data_in[6], cpu_data_in[5]
    } : 8'hzz;
    assign t0_dir = want_drive;
    assign t1_dir = want_drive;
    assign t0_oe_n = !armed;
    assign t1_oe_n = !armed;
    assign t2_dir = 1'b0;
    assign t2_oe_n = 1'b1;

    assign b0_dir = 1'b0;
    assign b1_dir = 1'b0;
    assign b2_dir = 1'b0;
    assign b0_oe_n = !armed;
    assign b1_oe_n = !armed;
    assign b2_oe_n = !armed;
    assign l0_dir = 1'b0;
    assign l1_dir = 1'b1;
    assign l2_dir = 1'b0;
    assign l0_oe_n = !armed;
    assign l1_oe_n = !armed;
    assign l2_oe_n = !armed;
    // Use the same responder acknowledgement as the internal CPU. There is
    // no socket-only read gate between the scope tap and this output.
    assign l1 = armed ? {4'b1111, berr_n, 2'b11, dtack_n} : 8'hzz;

    assign lx = halt_pull ? 1'b0 : 1'bz;
    assign ly = reset_pull ? 1'b0 : 1'bz;
    // Despite the schematic's _n name, TXS0108 OE is active high.
    assign xy_oe_n = armed;
    assign r0_dir = 1'b0;
    assign r1_dir = 1'b0;
    assign r2_dir = 1'b0;
    assign r0_oe_n = 1'b1;
    assign r1_oe_n = 1'b1;
    assign r2_oe_n = 1'b1;
    assign tclk = 1'b0;
    assign tclk_en = 1'b0;
    assign bclk = 1'b0;
    assign bclk_en = 1'b0;
    assign rclk = 1'b0;
    assign rclk_en = 1'b0;
    assign lclk = armed && cpu_clock;
    assign lclk_en = armed;

    // Q1 is P-channel: a high gate isolates DUT power. Never enable crowbar.
    assign dut_isolate = !armed;
    assign dut_crowbar = 1'b0;
    // Preserve only unused pins here. Keeping aliases of driven bidirectional
    // nets interferes with Efinity's top-level tri-state inference.
    (* syn_keep = "true" *)
    wire [47:0] dut_input_sample = {
        t2, b2[7], l0[7:4], l2[7:3], r0, r1, r2,
        tx, ty, bx, by, rx, ry
    };

endmodule
