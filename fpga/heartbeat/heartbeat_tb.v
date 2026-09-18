`timescale 1ns/1ps
module heartbeat_tb;
    reg clk = 0;
    wire heartbeat_out;
    wire nstatus_user, dut_isolate, dut_crowbar, psram_ce_n, xy_oe;
    wire f_lclk_en, f_tclk_en, f_bclk_en, f_rclk_en;
    wire [11:0] parallel_dir, parallel_oe_n;

    always #10 clk <= ~clk;

    heartbeat dut (
        .clk_50mhz(clk), .clk_50mhz_alias(clk),
        .heartbeat_out(heartbeat_out), .nstatus_user(nstatus_user),
        .dut_isolate(dut_isolate), .dut_crowbar(dut_crowbar),
        .psram_ce_n(psram_ce_n), .xy_oe(xy_oe),
        .f_lclk_en(f_lclk_en), .f_tclk_en(f_tclk_en),
        .f_bclk_en(f_bclk_en), .f_rclk_en(f_rclk_en),
        .parallel_dir(parallel_dir), .parallel_oe_n(parallel_oe_n)
    );

    initial begin
        #1;
        if ({nstatus_user, dut_isolate, dut_crowbar, psram_ce_n, xy_oe,
             f_lclk_en, f_tclk_en, f_bclk_en, f_rclk_en} !== 9'b010100000)
            $fatal(1, "unsafe scalar output state");
        if (parallel_dir !== 12'h000 || parallel_oe_n !== 12'hfff)
            $fatal(1, "unsafe parallel buffer state");
        force dut.half_period_count = 22'd2_499_999;
        #20;
        release dut.half_period_count;
        #1;
        if (heartbeat_out !== 1'b1)
            $fatal(1, "heartbeat did not toggle");
        $display("PASS: safe constants and heartbeat divider");
        $finish;
    end
endmodule
