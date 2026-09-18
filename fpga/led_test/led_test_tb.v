`timescale 1ns/1ps

module led_test_tb;
    reg clk = 1'b0;

    always #10 clk = ~clk;

    // Test the sequencer directly with a reduced observation window by
    // reaching its state registers. The complete wrapper is compiled in the
    // normal FPGA build, where the production half-second period is retained.
    integer bank;

    nuboard_led_test dut (
        .clk_50mhz(clk),
        .clk_50mhz_alias(clk)
    );

    initial begin
        for (bank = 0; bank < 12; bank = bank + 1) begin
            dut.bank_index = bank[3:0];

            dut.phase = dut.PHASE_OFF;
            #1;
            if (dut.bank_oe_n !== 12'hfff || dut.bank_dir !== 12'h000)
                $fatal(1, "bank %0d off phase is incorrect", bank);

            dut.phase = dut.PHASE_RED;
            #1;
            if (dut.bank_oe_n !== ~(12'b1 << bank) ||
                dut.bank_dir !== 12'h000)
                $fatal(1, "bank %0d red phase is incorrect", bank);

            if ({
                dut.r2_oe_n, dut.r1_oe_n, dut.r0_oe_n,
                dut.l2_oe_n, dut.l1_oe_n, dut.l0_oe_n,
                dut.b2_oe_n, dut.b1_oe_n, dut.b0_oe_n,
                dut.t2_oe_n, dut.t1_oe_n, dut.t0_oe_n
            } !== ~(12'b1 << bank))
                $fatal(1, "bank %0d OE output mapping is incorrect", bank);

            dut.phase = dut.PHASE_GREEN;
            #1;
            if (dut.bank_oe_n !== ~(12'b1 << bank) ||
                dut.bank_dir !== (12'b1 << bank))
                $fatal(1, "bank %0d green phase is incorrect", bank);

            if ({
                dut.r2_dir, dut.r1_dir, dut.r0_dir,
                dut.l2_dir, dut.l1_dir, dut.l0_dir,
                dut.b2_dir, dut.b1_dir, dut.b0_dir,
                dut.t2_dir, dut.t1_dir, dut.t0_dir
            } !== (12'b1 << bank))
                $fatal(1, "bank %0d DIR output mapping is incorrect", bank);
        end

        $display("PASS: all twelve bank LED states are decoded correctly");
        $finish;
    end
endmodule
