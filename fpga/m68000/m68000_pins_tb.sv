`timescale 1ns/1ps

// Exercise the real top-level pin adapter with its responder outputs forced.
// The clock never toggles: every direction/drive change must be combinational.
module m68000_pins_tb;
    reg [7:0] controls = 8'hff;
    wire [7:0] l0 = controls;
    wire [7:0] l1;
    wire [7:0] t0;
    wire [7:0] t1;
    wire t0_dir;
    wire t1_dir;
    wire t0_oe_n;
    wire t1_oe_n;

    nuboard_m68000 dut (
        .clk_50mhz(1'b0),
        .clk_50mhz_alias(1'b0),
        .spi_cs_n(1'b1),
        .spi_sck(1'b0),
        .spi_mosi(1'b0),
        .l0(l0),
        .l1(l1),
        .t0(t0),
        .t1(t1),
        .t0_dir(t0_dir),
        .t1_dir(t1_dir),
        .t0_oe_n(t0_oe_n),
        .t1_oe_n(t1_oe_n)
    );

    task check_drive(input bit expected, input bit armed);
        begin
            #1;
            if (dut.psram_ce_n !== 1'b1 || dut.psram_sclk !== 1'b0)
                $fatal(1, "unused PSRAM must remain deselected with clock low");
            if (t0_dir !== expected || t1_dir !== expected ||
                dut.want_drive !== expected)
                $fatal(1, "buffer DIR and FPGA drive did not switch immediately");
            if (t0_oe_n !== !armed || t1_oe_n !== !armed)
                $fatal(1, "data bank enables must follow socket arming");
            if (expected && (t0 !== 8'ha5 || t1 !== 8'hd2))
                $fatal(1, "read data did not reach the FPGA pins immediately");
        end
    endtask

    initial begin
        force dut.armed = 1'b0;
        force dut.cpu_data_in = 16'ha55a;
        force dut.dtack_n = 1'b1;
        force dut.berr_n = 1'b1;
        check_drive(0, 0);

        force dut.armed = 1'b1;
        // R/W is high but AS/UDS/LDS are inactive and the responder is idle.
        // Read drive must already be enabled, without waiting for data ready.
        check_drive(1, 1);

        // DTACK is forwarded without a separate socket-side read gate.
        force dut.dtack_n = 1'b0;
        #1;
        if (l1[0] !== 1'b0)
            $fatal(1, "socket acknowledgement was delayed");

        // All eight AS/UDS/LDS combinations retain drive while R/W is high.
        // In particular, the gaps between reads must not turn it off.
        for (int strobes = 0; strobes < 8; strobes = strobes + 1) begin
            controls[2:0] = 3'(strobes);
            check_drive(1, 1);
        end

        // Data can change while continuously driving, even in an idle gap.
        force dut.cpu_data_in = 16'h3c00;
        #1;
        if (!t0_dir || !t1_dir || t0 !== 8'h3c || t1 !== 8'h00)
            $fatal(1, "read data did not update while drive remained enabled");
        force dut.cpu_data_in = 16'ha55a;

        // Only R/W changes direction during an armed run. All write-strobe
        // combinations leave the external buffers enabled in input mode.
        controls[3] = 1'b0;
        for (int strobes = 0; strobes < 8; strobes = strobes + 1) begin
            controls[2:0] = 3'(strobes);
            check_drive(0, 1);
        end
        if (l1[0] !== 1'b0)
            $fatal(1, "write acknowledgement was gated");
        controls[3] = 1'b1;
        check_drive(1, 1);
        force dut.armed = 1'b0;
        check_drive(0, 0);

        $display("PASS: continuous read drive, R/W direction, direct ACK, disarm");
        $finish;
    end
endmodule
