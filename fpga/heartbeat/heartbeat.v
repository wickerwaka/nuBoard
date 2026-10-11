`timescale 1ns/1ps

// nuBoard FPGA configuration proof of concept.
//
// The only changing output is the 10 Hz heartbeat returned to the RP2040 on
// the configuration CSO pin after the device enters user mode.  Every output
// that can connect the DUT or the HyperRAM is held at its safe level.
module heartbeat (
    (* syn_peri_port = 0 *) input  wire clk_50mhz,
    (* syn_peri_port = 0 *) input  wire clk_50mhz_alias,
    (* syn_peri_port = 0 *) output wire heartbeat_out,
    (* syn_peri_port = 0 *) output wire nstatus_user,
    (* syn_peri_port = 0 *) output wire dut_isolate,
    (* syn_peri_port = 0 *) output wire dut_crowbar,
    (* syn_peri_port = 0 *) output wire hr_cs_n,
    (* syn_peri_port = 0 *) output wire hr_reset_n,
    (* syn_peri_port = 0 *) output wire xy_oe,
    (* syn_peri_port = 0 *) output wire f_lclk_en,
    (* syn_peri_port = 0 *) output wire f_tclk_en,
    (* syn_peri_port = 0 *) output wire f_bclk_en,
    (* syn_peri_port = 0 *) output wire f_rclk_en,
    (* syn_peri_port = 0 *) output wire [11:0] parallel_dir,
    (* syn_peri_port = 0 *) output wire [11:0] parallel_oe_n
);
    // 50 MHz / (2 * 2,500,000) = 10 Hz, with equal high and low times.
    reg [21:0] half_period_count = 22'd0;
    reg heartbeat = 1'b0;

    always @(posedge clk_50mhz) begin
        if (half_period_count == 22'd2_499_999) begin
            half_period_count <= 22'd0;
            heartbeat <= ~heartbeat;
        end else begin
            half_period_count <= half_period_count + 1'b1;
        end
    end

    assign heartbeat_out = heartbeat;
    assign nstatus_user = 1'b0;
    assign dut_isolate = 1'b1;
    assign dut_crowbar = 1'b0;
    // HyperRAM deselected and not in reset. Its CK, RWDS and DQ pins are
    // not driven; a deselected device ignores them.
    assign hr_cs_n = 1'b1;
    assign hr_reset_n = 1'b1;
    // Despite the active-low schematic net name, the XY buffer enable is
    // active high in the fitted hardware.  Low is the isolated state.
    assign xy_oe = 1'b0;
    assign f_lclk_en = 1'b0;
    assign f_tclk_en = 1'b0;
    assign f_bclk_en = 1'b0;
    assign f_rclk_en = 1'b0;
    assign parallel_dir = 12'h000;
    assign parallel_oe_n = 12'hfff;

    // A18 shares the oscillator PCB net with A20.  It is intentionally an
    // input and otherwise unused; keeping the port documents and constrains
    // the second physical connection without creating another clock source.
    wire unused_clk_alias = clk_50mhz_alias;
endmodule
