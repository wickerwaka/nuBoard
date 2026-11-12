`timescale 1ns/1ps

// build.sh writes V35S_MODEL_PRESENT: 1 when the model core is compiled in.
`include "v35s_build.vh"

// nuBoard revision 2 with the uPD70337 (V35S) daughterboard. Bank bit
// permutations come from hardware/v35s/pin-map.csv and directions from
// hardware/v35s/bank-modes.md. dir=1 drives toward the CPU.
module nuboard_v35s (
    // The whole design runs on one 33.33 MHz clock from PLL_TR1, referenced
    // to the 50 MHz oscillator on A18 (v35s.isf). One tick is 30 ns.
    (* syn_peri_port = 0 *) input wire clk_sys,
    (* syn_peri_port = 0 *) input wire sys_pll_locked,
    output wire        heartbeat_out,

    output wire        spi_miso,
    input  wire        spi_cs_n,
    input  wire        spi_sck,
    input  wire        spi_mosi,
    output wire        fpga_irq_n,

    output wire        dut_isolate,
    output wire        dut_crowbar,

    // HyperRAM is unused here; keep it deselected and quiet.
    output wire        hr_ck,
    output wire        hr_cs_n,
    output wire        hr_reset_n,
    inout  wire        hr_rwds,
    inout  wire [7:0]  hr_dq,

    inout  wire [7:0]  t0,
    input  wire [7:0]  t1,     // strobes: CPU to host only
    inout  wire [7:0]  t2,
    output wire        t0_dir,
    output wire        t1_dir,
    output wire        t2_dir,
    output wire        t0_oe_n,
    output wire        t1_oe_n,
    output wire        t2_oe_n,

    input  wire [7:0]  b0,     // A16-A19, /UBE, TxD: CPU to host only
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
    input  wire [7:0]  l2,     // A0 and multiplexed A9/A1..: CPU to host only
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

    // The V35S board leaves every sideband pin unconnected.
    inout  wire [3:0]  tx,
    inout  wire [3:0]  bx,
    inout  wire [3:0]  lx,
    inout  wire [3:0]  rx,
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
    localparam MODEL_PRESENT = `V35S_MODEL_PRESENT;

    wire input_valid, input_ready, input_last;
    wire output_valid, output_ready, output_last;
    wire [7:0] input_data, output_data;
    wire debug_valid, debug_write, debug_ready, debug_error;
    wire [19:0] debug_address;
    wire [15:0] debug_write_data, debug_read_data;

    assign hr_ck = 1'b0;
    assign hr_cs_n = 1'b1;
    assign hr_reset_n = 1'b0;
    assign hr_rwds = 1'bz;
    assign hr_dq = 8'hzz;

    nuboard_mailbox mailbox_link (
        .clk_50mhz(clk_sys),
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
        .clock(clk_sys),
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

    // D0..D7 on L0 and D8..D15 on L1 are pairwise swapped: bank bit 1 is
    // D2, bank bit 2 is D1, and so on. The permutation is its own inverse.
    function [7:0] data_swap;
        input [7:0] value;
        data_swap = {value[7], value[5], value[6], value[3],
                     value[4], value[1], value[2], value[0]};
    endfunction

    wire [15:0] cpu_data_out = {data_swap(l1), data_swap(l0)};
    // Pins A9/A1 (bit 0) through A17/A9 (bit 8).
    wire [8:0] cpu_mux_address = {
        b0[2], b0[3], l2[5], l2[7], l2[4], l2[6], l2[3], l2[2], l2[1]
    };

    wire [15:0] cpu_data_in;
    wire cpu_data_drive, cpu_vector_drive, cpu_ready, cpu_reset_n, x1;
    // power_on switches DUT power; translators and X1 follow powered_on,
    // which rises once the supply has settled.
    wire power_on, powered_on;
    wire armed = powered_on;
    wire [15:0] levels;
    wire [7:0] p0_levels, port_mode;

    v35s_harness #(.MODEL_PRESENT(MODEL_PRESENT)) harness (
        .clock(clk_sys),
        .debug_valid(debug_valid),
        .debug_write(debug_write),
        .debug_address(debug_address),
        .debug_write_data(debug_write_data),
        .debug_ready(debug_ready),
        .debug_error(debug_error),
        .debug_read_data(debug_read_data),
        .socket_a0(l2[0]),
        .socket_a19(b0[5]),
        .socket_a18_ube(b0[4]),
        .socket_mux_address(cpu_mux_address),
        .socket_data_out(cpu_data_out),
        .socket_mreq_n(t1[6]),
        .socket_mstb_n(t1[4]),
        .socket_iostb_n(t1[5]),
        .socket_read_write(t1[3]),
        .socket_refrq_n(t1[2]),
        .socket_p0(t2),
        .socket_p2_out({r0[7], r0[6], r0[5], r0[4], r0[3]}),
        .socket_r2(r2[3:0]),
        // T0 bit 7 is P14 (INT), bit 6 P17 (READY); B0 bits 6/7 are TxD0/TxD1.
        .socket_t0({t0[6], t0[7]}),
        .socket_txd({b0[7], b0[6]}),
        .socket_data_in(cpu_data_in),
        .socket_data_drive(cpu_data_drive),
        .socket_vector_drive(cpu_vector_drive),
        .socket_ready(cpu_ready),
        .socket_reset_n(cpu_reset_n),
        .input_levels(levels),
        .p0_levels(p0_levels),
        .port_mode(port_mode),
        .socket_armed(power_on),
        .socket_powered(powered_on),
        .x1(x1),
        .busy(),
        .complete()
    );

    // Bank modes: 0 = host drives the CPU (H), 1 = disabled (Z),
    // 2 = CPU drives the host (D).
    wire t2_h = port_mode[1:0] == 2'd0;
    wire t2_d = port_mode[1:0] == 2'd2;
    wire r2_h = port_mode[3:2] == 2'd0;
    wire r2_d = port_mode[3:2] == 2'd2;
    wire r0_h = port_mode[5:4] == 2'd0;
    wire r0_d = port_mode[5:4] == 2'd2;
    wire t0_h = port_mode[7:6] == 2'd0;
    wire t0_d = port_mode[7:6] == 2'd2;

    // Data: drive only while the lane answers a read strobe and the CPU
    // still signals a read. R//W is checked unsynchronized as a final guard.
    // The INTAK answer drives D7..D0 (L0) only, while /INTAK is low with R2
    // CPU-driven, R//W high and no refresh (the last two unsynchronized).
    wire data_drive = armed && cpu_data_drive && t1[3];
    wire vector_drive = armed && cpu_vector_drive && t1[3] && t1[2] && r2_d;
    wire low_drive = data_drive || vector_drive;
    assign l0 = low_drive ? data_swap(cpu_data_in[7:0]) : 8'hzz;
    assign l1 = data_drive ? data_swap(cpu_data_in[15:8]) : 8'hzz;
    assign l0_dir = low_drive;
    assign l1_dir = data_drive;
    assign l0_oe_n = !armed;
    assign l1_oe_n = !armed;

    // Address, strobes and the B0 outputs only ever flow toward the host;
    // those FPGA pins are inputs and have no output driver at all.
    assign l2_dir = 1'b0;
    assign b0_dir = 1'b0;
    assign t1_dir = 1'b0;
    assign l2_oe_n = !armed;
    assign b0_oe_n = !armed;
    assign t1_oe_n = !armed;

    // B1: RxD0, /RESET, /CTS1, RxD1, /INTP1, NMI, N//S, /INTP0.
    assign b1 = armed ? {
        levels[2], levels[0], levels[1], levels[3],
        levels[10], levels[12], cpu_reset_n, levels[9]
    } : 8'hzz;
    assign b1_dir = 1'b1;
    assign b1_oe_n = !armed;

    // B2: DMARQ0, DMARQ1, HLDRQ; unused bits are held low.
    assign b2 = armed ? {5'd0, levels[8], levels[7], levels[6]} : 8'hzz;
    assign b2_dir = 1'b1;
    assign b2_oe_n = !armed;

    // R1: PT0..PT7 comparator inputs, held low.
    assign r1 = armed ? 8'h00 : 8'hzz;
    assign r1_dir = 1'b1;
    assign r1_oe_n = !armed;

    // T0: READY (bit 6) and INT//POLL (bit 7); unused bits low.
    assign t0 = armed && t0_h ? {levels[5], cpu_ready, 6'd0} : 8'hzz;
    assign t0_dir = t0_h;
    assign t0_oe_n = !armed || !(t0_h || t0_d);

    // T2: P00..P07/CLKOUT. Inputs at reset, so the host drives them until a
    // marker hands the bank over.
    assign t2 = armed && t2_h ? p0_levels : 8'hzz;
    assign t2_dir = t2_h;
    assign t2_oe_n = !armed || !(t2_h || t2_d);

    // R2: /CTS0, /INTP2, TOUT, /SCK0; unused bits low.
    assign r2 = armed && r2_h ? {4'd0, 1'b0, 1'b0, levels[4], levels[11]} : 8'hzz;
    assign r2_dir = r2_h;
    assign r2_oe_n = !armed || !(r2_h || r2_d);

    // R0: P21//DMAAK0, P22//TC0, P24//DMAAK1, P26//HLDAK, P25//TC1. P2 is
    // an input port after reset; drive it low until handed over.
    assign r0 = armed && r0_h ? 8'h00 : 8'hzz;
    assign r0_dir = r0_h;
    assign r0_oe_n = !armed || !(r0_h || r0_d);

    // X1 on RCLK and its complement X2 on TCLK.
    assign rclk = armed && x1;
    assign tclk = armed && !x1;
    assign rclk_en = armed;
    assign tclk_en = armed;
    assign lclk = 1'b0;
    assign lclk_en = 1'b0;
    assign bclk = 1'b0;
    assign bclk_en = 1'b0;

    // TXS0108 OE is active high despite the net name; leave it disabled.
    assign xy_oe_n = 1'b0;

    // Q1 is P-channel: a high gate isolates DUT power. Never enable crowbar.
    assign dut_isolate = !power_on;
    assign dut_crowbar = 1'b0;

    (* syn_keep = "true" *)
    wire [16:0] dut_input_sample = {sys_pll_locked, tx, bx, lx, rx};
endmodule
